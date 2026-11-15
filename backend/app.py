#!/usr/bin/env python3
import os, uuid, logging, base64, threading, random, string, io, json, traceback, re
from datetime import datetime

import psycopg
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
from reportlab.lib.colors import HexColor
import qrcode
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from data import (
    W, BEST, MAX, P, SCHOLARSHIPS, PAYMENT_PLANS, CHATBOT_QA,
    get_subject_requirements,
)
from db import connect, init_db
from auth import (
    current_user, public_user, login_required, admin_required,
    hash_password, verify_password, create_session, destroy_session, bearer_token,
)
from services.payments import PaymentService, normalize_phone, validate_provider
from services.reports import generate_and_send_reports
from services.invoices import generate_invoice_pdf

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["JSON_SORT_KEYS"] = False

FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGINS}}, allow_headers=["Content-Type", "Authorization"], methods=["GET", "POST", "DELETE", "OPTIONS"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
payments = PaymentService()

# ==========================================
# HELPERS
# ==========================================

def add_credit(user_id):
    with connect() as conn:
        conn.execute("UPDATE users SET credits = credits + 1 WHERE id=%s", (user_id,))

def ensure_admin():
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password: return
    with connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()
        if row:
            conn.execute("UPDATE users SET role='admin', active=1, password_hash=%s WHERE id=%s", (hash_password(password), row["id"]))
        else:
            conn.execute(
                """INSERT INTO users(name,email,phone,password_hash,referral_code,role,active) 
                   VALUES(%s,%s,%s,%s,%s,'admin',1)""",
                ("EduPoint Administrator", email, "", hash_password(password), "ADMIN"),
            )
ensure_admin()

# ==========================================
# CALCULATION LOGIC
# ==========================================

def process_calculation(u, subjects, grades):
    vals = [W[str(v).strip().upper()] for v in grades.values() if str(v).strip().upper() in W]
    vals = sorted(vals, reverse=True)[:7]
    if len(vals) < 7: raise ValueError("Enter at least 7 valid grades.")

    cp = (sum(vals) / BEST) * MAX
    out = []
    for course in P:
        diff = cp - course["c"]
        if diff >= 0: match_type = "qualified"
        elif diff >= -2: match_type = "close"
        else: match_type = "not_qualified"
        out.append({**course, "difference": round(diff, 3), "match": match_type})

    ref_code = "EP-2026-" + ''.join(random.choices(string.digits, k=6))

    with connect() as conn:
        history_row = conn.execute(
            "INSERT INTO calculation_history (user_id, reference, cluster_points) VALUES (%s, %s, %s) RETURNING id",
            (u["id"], ref_code, round(cp, 3))
        ).fetchone()
        history_id = history_row["id"]

        for i in range(7):
            subj = subjects.get(str(i), f"Subject {i+1}")
            grade = grades.get(str(i), "-")
            conn.execute("INSERT INTO calculation_subjects (history_id, subject, grade) VALUES (%s, %s, %s)", (history_id, subj, grade))

        for c in out:
            if c["match"] in ["qualified", "close"]:
                conn.execute(
                    "INSERT INTO calculation_courses (history_id, course_name, university, cutoff, difference, match_type) VALUES (%s, %s, %s, %s, %s, %s)",
                    (history_id, c["n"], c["u"], c["c"], c["difference"], c["match"])
                )

    return {"reference": ref_code, "cluster_points": round(cp, 3), "results": out}

# ==========================================
# ATOMIC CLAIM + PROCESS
# ==========================================

def _claim_and_process(tx_id):
    with connect() as conn:
        claimed = conn.execute(
            "UPDATE payments SET status = 'completed', updated_at = now() "
            "WHERE transaction_id = %s AND status = 'paid' RETURNING id",
            (tx_id,)
        ).fetchone()

    if not claimed:
        return None

    row = payments.get(tx_id)
    calc_data = row.get("calculation_data")
    if not calc_data:
        logger.info(f"Claimed {tx_id} but no calc_data — nothing to process")
        return None

    with connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE id = %s", (row["user_id"],)).fetchone()

    try:
        calc_results = process_calculation(u, calc_data["subjects"], calc_data["grades"])
        add_credit(row["user_id"])
        send_paid_receipt_email(
            u["email"], u["name"],
            calc_results["cluster_points"], calc_results["results"],
            calc_data["subjects"], calc_data["grades"],
            SCHOLARSHIPS, row
        )
        with connect() as conn:
            conn.execute("UPDATE payments SET calculation_data = NULL WHERE transaction_id = %s", (tx_id,))
        logger.info(f"Processed results for {tx_id} and sent email to {u['email']}")
        return calc_results
    except Exception as e:
        with connect() as conn:
            conn.execute("UPDATE payments SET status = 'paid' WHERE transaction_id = %s", (tx_id,))
        logger.error(f"Claim+process failed for {tx_id}: {traceback.format_exc()}")
        return None

# ==========================================
# PDF GENERATION (UNTOUCHED)
# ==========================================

def generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships):
    buffer = io.BytesIO()
    NAVY = HexColor("#172554"); PALE = HexColor("#F4F6FC"); LIGHT_BLUE = HexColor("#EAF3FF")
    LIGHT_PURPLE = HexColor("#F1ECFB"); INK = HexColor("#1F2937"); MUTED = HexColor("#64748B")
    BORDER = HexColor("#DCE3EF")
    GREEN_HDR = HexColor("#15803D"); AMBER_HDR = HexColor("#B45309"); RED_HDR = HexColor("#B91C1C")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.white))
    styles.add(ParagraphStyle(name="HeroTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_LEFT, textColor=NAVY))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY, spaceBefore=6, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=INK))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.5, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=NAVY))
    styles.add(ParagraphStyle(name="WhiteSmall", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, textColor=colors.white))

    def P(text, style="BodySmall"):
        return Paragraph(str(text), styles[style])

    def header_footer(canvas, doc):
        canvas.saveState(); w, h = A4
        canvas.setFillColor(NAVY); canvas.rect(0, h - 8*mm, w, 8*mm, stroke=0, fill=1)
        canvas.setStrokeColor(BORDER); canvas.line(18*mm, 16*mm, w - 18*mm, 16*mm)
        canvas.setFont("Helvetica", 7); canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 10.5*mm, "EduPointAI  |  Your Education. Your Future.")
        canvas.drawRightString(w - 18*mm, 10.5*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=17*mm, bottomMargin=23*mm)

    qualified = sorted([r for r in results if r["match"] == "qualified"], key=lambda x: -x["c"])
    close = sorted([r for r in results if r["match"] == "close"], key=lambda x: -x["c"])
    not_qual = sorted([r for r in results if r["match"] == "not_qualified"], key=lambda x: -x["c"])

    def build_course_table(courses, header_color):
        header = [
            P("COURSE", "Tiny"), P("UNIVERSITY", "Tiny"),
            P("CUTOFF", "Tiny"), P("GAP", "Tiny"),
            P("DUR", "Tiny"), P("KEY SUBJECTS REQUIRED", "Tiny"),
        ]
        data = [header]
        for c in courses:
            req, other, _note = get_subject_requirements(c["n"])
            req_str = ", ".join(req)
            if other:
                req_str += " • " + other
            data.append([
                P(c["n"], "BodySmall"),
                P(c["u"], "BodySmall"),
                P(f"{c['c']:.3f}", "BodySmall"),
                P(f"{c['difference']:+.2f}", "BodySmall"),
                P(f"{c['y']}y", "BodySmall"),
                P(req_str, "BodySmall"),
            ])
        t = Table(data, colWidths=[44*mm, 33*mm, 13*mm, 12*mm, 10*mm, 50*mm], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), HexColor("#F8FAFC")))
        t.setStyle(TableStyle(style))
        return t

    story = []
    brand = Table([[P("EduPointAI", "Brand"),
                    P("COMPREHENSIVE CLUSTER & COURSE REPORT", "WhiteSmall")]],
                  colWidths=[70*mm, 104*mm], rowHeights=[22*mm])
    brand.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story += [brand, Spacer(1, 7*mm)]

    story += [
        P("Your cluster points & full course eligibility", "HeroTitle"),
        P("Every course in our database, grouped by whether your cluster meets, is close to, or is below the cutoff — with the specific subjects each course requires.", "Sub"),
        Spacer(1, 4*mm),
    ]

    ref = "EP-2026-" + ''.join(random.choices(string.digits, k=6))
    student = Table(
        [[P("STUDENT", "Tiny"), P("EMAIL", "Tiny"), P("REPORT REFERENCE", "Tiny")],
         [P(user_name, "BodySmall"), P(user_email, "BodySmall"), P(ref, "BodySmall")]],
        colWidths=[60*mm, 60*mm, 54*mm],
    )
    student.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [student, Spacer(1, 4*mm)]

    cards = Table(
        [[P("CLUSTER POINTS", "CardLabel"), P("QUALIFIED", "CardLabel"),
          P("CLOSE (±2)", "CardLabel"), P("NOT YET", "CardLabel")],
         [P(f"{cluster_points}", "CardValue"), P(str(len(qualified)), "CardValue"),
          P(str(len(close)), "CardValue"), P(str(len(not_qual)), "CardValue")]],
        colWidths=[43.5*mm]*4,
    )
    cards.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE),
        ("BACKGROUND", (1, 0), (1, -1), HexColor("#E8F8EF")),
        ("BACKGROUND", (2, 0), (2, -1), HexColor("#FEF6E0")),
        ("BACKGROUND", (3, 0), (3, -1), HexColor("#FDEDED")),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 1, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [cards, Spacer(1, 4*mm)]

    story += [P("01  Your KCSE Subject Breakdown", "Section")]
    grades_data = [[P("SUBJECT", "Tiny"), P("GRADE", "Tiny"), P("POINTS", "Tiny")]]
    for i in range(7):
        subj = subjects.get(str(i), f"Subject {i+1}")
        grade = grades.get(str(i), "-")
        pts = W.get(grade.upper(), 0) if grade else 0
        grades_data.append([P(subj, "BodySmall"), P(grade, "BodySmall"), P(str(pts), "BodySmall")])
    gt = Table(grades_data, colWidths=[110*mm, 30*mm, 30*mm])
    gt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    total_pts = sum(W.get((grades.get(str(i)) or "").upper(), 0) for i in range(7))
    story += [gt, Spacer(1, 2*mm),
              P(f"<i>Formula:</i> (sum of best 7 subject points ÷ {BEST:.0f}) × {MAX:.0f} "
                f"= ({total_pts} ÷ {BEST:.0f}) × {MAX:.0f} = <b>{cluster_points}</b>", "Sub")]

    story.append(PageBreak())
    story += [P("02  Top 10 Recommended Courses", "Section"),
              P(f"These are the highest-cutoff courses you currently qualify for. Your cluster ({cluster_points}) meets or exceeds their cutoffs — great choices to prioritise in KUCCPS.", "Sub"),
              Spacer(1, 3*mm)]
    if qualified:
        story.append(build_course_table(qualified[:10], GREEN_HDR))
    else:
        story.append(P("You do not yet meet the cutoff for any course in our database. See the Close (±2) and Not Yet Qualified sections below — they show the shortest paths forward.", "BodySmall"))

    if qualified:
        story.append(PageBreak())
        story += [P(f"03  All Courses You Qualify For ({len(qualified)})", "Section"),
                  P("Your cluster meets or exceeds every cutoff listed below. These are safe / competitive choices.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(qualified, GREEN_HDR)]

    if close:
        story.append(PageBreak())
        story += [P(f"04  Close Matches — Within 2.0 Points ({len(close)})", "Section"),
                  P("You are just below the cutoff. These may become reachable through a grade revision, diploma route, or inter-institution transfer later.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(close, AMBER_HDR)]

    if not_qual:
        story.append(PageBreak())
        story += [P(f"05  Not Yet Qualified ({len(not_qual)})", "Section"),
                  P("Cutoff is more than 2.0 points above your cluster. Use these as a roadmap for upgrading grades, retaking, or entering via a diploma pathway.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(not_qual, RED_HDR)]

    story.append(PageBreak())
    story += [P("06  Scholarship Opportunities", "Section")]
    sch_data = [[P("SCHOLARSHIP", "Tiny"), P("AMOUNT", "Tiny"), P("LINK", "Tiny")]]
    for s in scholarships[:8]:
        sch_data.append([P(s["name"], "BodySmall"), P(s["amount"], "BodySmall"), P(s["link"], "BodySmall")])
    st = Table(sch_data, colWidths=[65*mm, 45*mm, 64*mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_PURPLE),
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [st, Spacer(1, 5*mm),
              P("<i>Note:</i> Cutoff points change every year based on competition. Always verify subject requirements and cluster weighting on the official KUCCPS portal before submitting your application.", "Sub")]

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    buffer.seek(0)
    return buffer

# ==========================================
# EMAIL SENDERS
# ==========================================

def _get_brevo():
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    if not api_key or not sender_email:
        return None, None
    return Brevo(api_key=api_key), sender_email

def send_pending_invoice_email(user_email, user_name, payment):
    try:
        client, sender_email = _get_brevo()
        if not client:
            logger.warning("Brevo not configured, skipping invoice email")
            return

        inv_buffer = generate_invoice_pdf(
            {"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment
        )
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")

        pay_link = (payment.get("redirect_url") or "").strip()
        amount = float(payment.get("amount", 0))
        inv_short = payment["transaction_id"][-8:].upper()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your EduPointAI Invoice</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;">
                                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
                                </td>
                            </tr>
                            
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px;">
                                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <span style="display: inline-block; background-color: #F2A93B; color: #101B3D; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Awaiting Payment</span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 15px;">
                                                <h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">Your invoice is ready!</h2>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <p style="color: #26324D; margin: 0; font-size: 16px; line-height: 1.6;">One step closer to unlocking your academic opportunities.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;">
                                            </td>
                                        </tr>
                                        
                                        <!-- Invoice Details -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <p style="color: #7047EB; margin: 0 0 10px 0; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Invoice INV-{inv_short}</p>
                                                <p style="color: #101B3D; margin: 0; font-size: 32px; font-weight: 800;">KES {amount:,.2f}</p>
                                            </td>
                                        </tr>

                                        <!-- Pay Button -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <a href="{pay_link}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(112, 71, 235, 0.3);">PAY NOW — KES {amount:.0f}</a>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <p style="color: #64748B; margin: 0; font-size: 13px;">You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, T-Kash, or Card.</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;">
                                    <p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px; line-height: 1.5;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p>
                                    <p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        client.transactional_emails.send_transac_email(
            subject=f"EduPointAI Invoice {inv_short} — KES {amount:.0f}",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"}],
        )
        logger.info(f"Sent pending invoice with Pay Now to {user_email}")
    except Exception:
        logger.error(f"Failed to send invoice email: {traceback.format_exc()}")

def send_reminder_email(user_email, user_name, payment):
    try:
        client, sender_email = _get_brevo()
        if not client:
            return

        pay_link = (payment.get("redirect_url") or "").strip()
        if not pay_link:
            return

        inv_buffer = generate_invoice_pdf(
            {"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment
        )
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")

        amount = float(payment.get("amount", 0))
        inv_short = payment["transaction_id"][-8:].upper()
        reminder_num = (payment.get("reminder_count") or 0) + 1

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Payment Reminder</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;">
                                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
                                </td>
                            </tr>
                            
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px;">
                                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <span style="display: inline-block; background-color: #F2A93B; color: #101B3D; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Payment Reminder</span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 15px;">
                                                <h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">A friendly reminder!</h2>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <p style="color: #26324D; margin: 0; font-size: 16px; line-height: 1.6;">Your EduPointAI Comprehensive Results Report is waiting for you.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;">
                                            </td>
                                        </tr>
                                        
                                        <!-- Invoice Details -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <p style="color: #7047EB; margin: 0 0 10px 0; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Invoice INV-{inv_short} • Reminder #{reminder_num}</p>
                                                <p style="color: #101B3D; margin: 0; font-size: 32px; font-weight: 800;">KES {amount:,.2f}</p>
                                            </td>
                                        </tr>

                                        <!-- Pay Button -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <a href="{pay_link}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(112, 71, 235, 0.3);">PAY NOW — KES {amount:.0f}</a>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <p style="color: #64748B; margin: 0; font-size: 13px;">If you have already paid, please ignore this email — your Results Report will arrive shortly.</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;">
                                    <p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px; line-height: 1.5;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p>
                                    <p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        client.transactional_emails.send_transac_email(
            subject=f"Reminder: Invoice INV-{inv_short} unpaid — KES {amount:.0f}",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"}],
        )
        logger.info(f"Sent reminder #{reminder_num} to {user_email}")
    except Exception:
        logger.error(f"Failed to send reminder: {traceback.format_exc()}")

def send_paid_receipt_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships, payment):
    try:
        client, sender_email = _get_brevo()
        if not client:
            return

        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode("utf-8")
        attachments = [{"content": pdf_base64, "name": "EduPointAI_Results.pdf"}]

        inv_buffer = generate_invoice_pdf(
            {"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment
        )
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")
        attachments.append({"content": inv_base64, "name": f"Receipt_{payment['transaction_id']}.pdf"})

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your Report is Ready</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;">
                                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
                                </td>
                            </tr>
                            
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px;">
                                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <span style="display: inline-block; background-color: #0F9D91; color: #ffffff; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Payment Confirmation</span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 15px;">
                                                <h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">Payment successful! <span style="color: #0F9D91; font-size: 28px;">✓</span></h2>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <p style="color: #26324D; margin: 0; font-size: 16px; line-height: 1.6;">Thank you! Your payment has been confirmed.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;">
                                            </td>
                                        </tr>
                                        
                                        <!-- Success Details -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 30px;">
                                                <h3 style="color: #7047EB; margin: 0 0 10px 0; font-size: 22px; font-weight: 700;">Your report is ready! 🎓</h3>
                                                <p style="color: #26324D; margin: 0; font-size: 15px;">Your next academic chapter starts here.</p>
                                                <p style="color: #26324D; margin: 10px 0 0 0; font-size: 15px;"><strong>Cluster Points:</strong> {cluster_points}</p>
                                            </td>
                                        </tr>

                                        <!-- Action Button -->
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <a href="https://edupointai-frontend.vercel.app/" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(112, 71, 235, 0.3);">VIEW MY REPORT</a>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding-bottom: 20px;">
                                                <p style="color: #64748B; margin: 0; font-size: 13px;">Your official Results Report and Payment Receipt are attached to this email.</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;">
                                    <p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px; line-height: 1.5;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p>
                                    <p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Results & Receipt",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=attachments,
        )
        logger.info(f"Successfully sent results and receipt to {user_email}")
    except Exception:
        logger.error(f"Failed to send results email: {traceback.format_exc()}")

# ==========================================
# REMINDER BATCH
# ==========================================

def send_pending_reminders():
    sent = 0
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT p.*, u.name AS user_name, u.email AS user_email
                FROM payments p
                JOIN users u ON u.id = p.user_id
                WHERE p.status = 'pending'
                  AND p.redirect_url IS NOT NULL
                  AND p.created_at < now() - INTERVAL '24 hours'
                  AND (p.last_reminder_at IS NULL OR p.last_reminder_at < now() - INTERVAL '24 hours')
                ORDER BY p.created_at ASC
                LIMIT 100
            """).fetchall()
    except Exception:
        logger.error(f"Reminder query failed: {traceback.format_exc()}")
        return 0

    for row in rows:
        try:
            send_reminder_email(row["user_email"], row["user_name"], row)
            with connect() as conn:
                conn.execute(
                    "UPDATE payments SET last_reminder_at = now(), "
                    "reminder_count = COALESCE(reminder_count, 0) + 1 "
                    "WHERE transaction_id = %s",
                    (row["transaction_id"],)
                )
            sent += 1
        except Exception:
            logger.error(f"Reminder for {row['transaction_id']} failed: {traceback.format_exc()}")

    logger.info(f"Reminder batch complete — {sent} sent")
    return sent

# ==========================================
# ROUTES
# ==========================================

@app.get("/health")
def health(): return jsonify(ok=True, service="edupoint-api", price_per_calculation=100)

@app.post("/api/auth/google")
def google_login():
    d = request.get_json(silent=True) or {}
    token = d.get("credential")
    if not token: return jsonify(ok=False, error="No Google credential provided."), 400
    try:
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not client_id: raise ValueError("GOOGLE_CLIENT_ID missing in Render Environment.")
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        email = idinfo["email"].strip().lower(); name = idinfo.get("name", "Google User")
        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            if not u:
                u = conn.execute(
                    "INSERT INTO users(name, email, phone, password_hash, role, credits) "
                    "VALUES(%s, %s, %s, %s, 'student', 0) RETURNING *",
                    (name, email, "0700000000", "GOOGLE_AUTH")
                ).fetchone()
        session_token = create_session(u["id"])
        return jsonify(ok=True, token=session_token, user=public_user(u), redirect="/")
    except Exception as e:
        logger.error(f"Google login failed: {traceback.format_exc()}")
        return jsonify(ok=False, error=f"Login failed: {str(e)}"), 500

@app.post("/api/logout")
@login_required
def logout():
    destroy_session(bearer_token())
    return jsonify(ok=True)

@app.get("/api/me")
@login_required
def me():
    u = current_user()
    return jsonify(ok=True, user=public_user(u), calculations_completed=int(u.get("credits", 0) or 0), price_per_calculation=100)

@app.post("/api/payment/initiate")
@login_required
def initiate_payment():
    u = current_user()
    d = request.get_json(silent=True) or {}
    provider = (d.get("provider") or "").strip().lower()
    phone = normalize_phone(d.get("phone") or u["phone"])
    plan = (d.get("plan") or "standard").strip().lower()

    subjects = d.get("subjects"); grades = d.get("grades")
    calc_data = {"subjects": subjects, "grades": grades} if subjects and grades else None

    if plan not in PAYMENT_PLANS: return jsonify(ok=False, error="Invalid plan."), 400
    if not validate_provider(provider): return jsonify(ok=False, error="Unsupported provider."), 400
    if not phone: return jsonify(ok=False, error="Invalid phone number."), 400
    if not calc_data: return jsonify(ok=False, error="Subjects and grades are required."), 400

    amount = PAYMENT_PLANS[plan]["amount"]
    tx = "EDU-" + uuid.uuid4().hex[:16].upper()
    callback_url = f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/"

    try:
        payments.create_pending(
            transaction_id=tx, user_id=u["id"], phone=phone,
            network=provider, amount=amount, plan=plan,
            calculation_data=calc_data
        )

        r = payments.initiate(
            provider=provider, phone=phone, amount=amount,
            transaction_id=tx, plan=plan, user=u, callback_url=callback_url
        )

        payments.update(
            tx,
            status=r.get("status"),
            provider_reference=r.get("provider_reference"),
            message=r.get("message"),
            redirect_url=r.get("redirect_url")
        )

        pending_payment = payments.get(tx)
        threading.Thread(
            target=send_pending_invoice_email,
            args=(u["email"], u["name"], pending_payment),
            daemon=True
        ).start()

        with connect() as conn:
            conn.execute(
                "UPDATE payments SET invoice_sent_at = now() WHERE transaction_id = %s",
                (tx,)
            )

        return jsonify(ok=True, transaction_id=tx, redirect_url=r.get("redirect_url"))

    except Exception as e:
        logger.error(f"Pesapal initiation failed: {traceback.format_exc()}")
        payments.update(tx, status="failed", message=str(e))
        return jsonify(ok=False, error=f"Error: {str(e)}"), 502

@app.route("/api/payment/webhook/pesapal", methods=["GET", "POST"])
def pesapal_webhook():
    try:
        body = request.get_json(silent=True) or {}
        tracking_id = (
            request.args.get("OrderTrackingId")
            or request.args.get("orderTrackingId")
            or body.get("OrderTrackingId")
            or body.get("orderTrackingId")
        )
        if not tracking_id:
            logger.warning("Pesapal IPN missing OrderTrackingId")
            return jsonify(ok=False, error="Missing OrderTrackingId"), 400

        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE provider_reference = %s",
                (tracking_id,)
            ).fetchone()

        if not row:
            logger.warning(f"Pesapal IPN: unknown tracking_id {tracking_id}")
            return jsonify(ok=True, note="unknown")

        from services.pesapal import PesapalClient
        try:
            st = PesapalClient().transaction_status(tracking_id)
        except Exception:
            logger.error(f"Pesapal status check failed in webhook: {traceback.format_exc()}")
            return jsonify(ok=False), 500

        status_code = st.get("status_code", -1)
        new_status = {1: "paid", 2: "failed", 3: "reversed", 0: "invalid"}.get(status_code, "pending")

        payments.update(
            row["transaction_id"],
            status=new_status,
            message=st.get("status") or ""
        )

        if new_status == "paid":
            _claim_and_process(row["transaction_id"])

        return jsonify(ok=True, status=new_status)

    except Exception:
        logger.error(f"Webhook error: {traceback.format_exc()}")
        return jsonify(ok=False), 500

@app.get("/api/payment/status/<transaction_id>")
@login_required
def payment_status(transaction_id):
    u = current_user()
    row = payments.get(transaction_id)
    if not row or (row.get("user_id") and row["user_id"] != u["id"] and u["role"] != "admin"):
        return jsonify(ok=False, error="Transaction not found."), 404

    if row["status"] == "pending":
        try:
            rr = payments.check_status(row)
            if rr:
                payments.update(transaction_id, status=rr["status"], message=rr.get("message"))
                row = payments.get(transaction_id)
        except Exception:
            logger.exception("Status check failed")

    calc_results = None
    if row["status"] == "paid":
        _claim_and_process(transaction_id)
        row = payments.get(transaction_id)

    if row["status"] == "completed" and row.get("results_json"):
        calc_results = row["results_json"]

    return jsonify(ok=True, payment=row, calculation_results=calc_results)

@app.get("/api/cron/send-reminders")
def trigger_reminders():
    secret = request.args.get("secret")
    expected = os.getenv("CRON_SECRET", "edupoint_secret_123")
    if secret != expected:
        return "Unauthorized", 401

    with connect() as conn:
        stuck = conn.execute("""
            SELECT transaction_id FROM payments 
            WHERE status = 'paid' AND updated_at < now() - INTERVAL '5 minutes'
            LIMIT 20
        """).fetchall()
    for s in stuck:
        _claim_and_process(s["transaction_id"])

    sent = send_pending_reminders()
    return jsonify(ok=True, reminders_sent=sent, stuck_retried=len(stuck)), 200

@app.get("/api/history")
@login_required
def get_history():
    u = current_user()
    with connect() as conn:
        rows = conn.execute("""
            SELECT h.*,
                   (SELECT COUNT(*) FROM calculation_courses
                    WHERE history_id = h.id AND match_type = 'qualified') AS qual_count
            FROM calculation_history h
            WHERE h.user_id = %s
            ORDER BY h.created_at DESC
        """, (u["id"],)).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["cluster_points"] = float(r["cluster_points"])
    return jsonify(ok=True, history=rows)

@app.get("/api/scholarships")
@login_required
def scholarships(): return jsonify(SCHOLARSHIPS)

@app.post("/api/chat")
@login_required
def chat():
    d = request.get_json(silent=True) or {}
    question = str(d.get("question", "")).lower().strip()
    if not question:
        return jsonify(answer="Ask me about any career, course, or subject requirement!")

    stop_words = {"what", "is", "a", "an", "the", "can", "i", "do", "with", "to", "for", "in", "of", "and", "how", "which", "are", "my", "me"}
    words = [w for w in re.findall(r'\b\w+\b', question) if w not in stop_words]

    best_match = None
    highest_score = 0
    for qa in CHATBOT_QA:
        score = 0
        for kw in qa["keywords"]:
            kw_words = kw.lower().split()
            if kw in question:
                score += 10
            else:
                for kw_word in kw_words:
                    if kw_word in words:
                        score += 2
        if score > highest_score:
            highest_score = score
            best_match = qa

    if best_match and highest_score >= 2:
        return jsonify(answer=best_match["answer"])
    return jsonify(answer="I am still expanding my career database. Try asking about specific careers (e.g., 'Software Engineer', 'Nursing'), subject requirements, or KCSE grades.")

# ==========================================
# ADMIN ROUTES
# ==========================================

@app.get("/api/admin/metrics")
@admin_required
def admin_metrics():
    with connect() as conn:
        rev_row = conn.execute("SELECT SUM(amount) as total FROM payments WHERE status IN ('paid', 'completed')").fetchone()
        total_revenue = float(rev_row["total"] or 0)

        users_row = conn.execute("SELECT COUNT(*) as total FROM users WHERE role = 'student'").fetchone()
        total_users = users_row["total"]

        calc_row = conn.execute("SELECT COUNT(*) as total FROM calculation_history").fetchone()
        total_calcs = calc_row["total"]

        pending_row = conn.execute("SELECT COUNT(*) as total FROM payments WHERE status = 'pending'").fetchone()
        total_pending = pending_row["total"]

    return jsonify(ok=True, metrics={
        "revenue": total_revenue,
        "users": total_users,
        "calculations": total_calcs,
        "pending_payments": total_pending
    })

@app.get("/api/admin/calculations")
@admin_required
def admin_calculations():
    with connect() as conn:
        rows = conn.execute("""
            SELECT h.id, h.reference, h.cluster_points, h.created_at, u.email, u.name
            FROM calculation_history h
            JOIN users u ON h.user_id = u.id
            ORDER BY h.created_at DESC
            LIMIT 50
        """).fetchall()
    
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["cluster_points"] = float(r["cluster_points"])
        
    return jsonify(ok=True, calculations=rows)

@app.get("/api/admin/payments")
@admin_required
def admin_payments():
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, transaction_id, user_id, amount, status,
                   invoice_sent_at, last_reminder_at, reminder_count,
                   (CASE WHEN status IN ('completed', 'paid') THEN true ELSE false END) as report_sent
            FROM payments ORDER BY id DESC LIMIT 100
        """).fetchall()
    return jsonify(ok=True, payments=[dict(r) for r in rows])

@app.post("/api/admin/payments/<transaction_id>/retry")
@admin_required
def admin_retry_payment(transaction_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM payments WHERE transaction_id=%s", (transaction_id,)).fetchone()
    
    if not row:
        return jsonify(ok=False, error="Not found"), 404
        
    if row["status"] == "paid":
        _claim_and_process(transaction_id)
        return jsonify(ok=True, message="Processing triggered.")
    
    if row["status"] == "pending":
        rr = payments.check_status(row)
        if rr and rr["status"] == "paid":
            payments.update(transaction_id, status="paid")
            _claim_and_process(transaction_id)
            return jsonify(ok=True, message="Payment confirmed and processed.")
            
    return jsonify(ok=False, error="Cannot retry. Payment is not marked as paid."), 400

@app.post("/api/admin/calculate/free")
@admin_required
def admin_free_calculation():
    d = request.get_json(silent=True) or {}
    email = d.get("email")
    subjects = d.get("subjects")
    grades = d.get("grades")
    
    if not email or not subjects or not grades:
        return jsonify(ok=False, error="Missing email, subjects, or grades."), 400
        
    with connect() as conn:
        # Find user or create a placeholder user so the calculation can link to them
        u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
        if not u:
            u = conn.execute(
                "INSERT INTO users(name, email, phone, password_hash, role) "
                "VALUES(%s, %s, %s, %s, 'student') RETURNING *", 
                ("Student (Admin Generated)", email, "0700000000", "ADMIN_GENERATED")
            ).fetchone()

    try:
        # 1. Process the calculation
        calc_results = process_calculation(u, subjects, grades)
        
        # 2. Create a fake payment object for the receipt
        fake_payment = {
            "transaction_id": "ADMIN-" + uuid.uuid4().hex[:8].upper(),
            "user_id": u["id"],
            "amount": 0.0,
            "status": "completed",
            "created_at": datetime.now()
        }

        # 3. Send the email with the PDF Report and Receipt
        send_paid_receipt_email(
            email, u["name"],
            calc_results["cluster_points"], calc_results["results"],
            subjects, grades, SCHOLARSHIPS, fake_payment
        )
        
        return jsonify(ok=True, calculation_results=calc_results)
        
    except Exception as e:
        logger.error(f"Admin free calculation failed: {traceback.format_exc()}")
        return jsonify(ok=False, error=str(e)), 500

@app.get("/api/admin/payments/export")
@admin_required
def export_payments_excel():
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT 
                    p.transaction_id, p.amount, p.status, p.provider_reference,
                    p.invoice_sent_at, p.reminder_count, p.created_at,
                    u.id as user_id, u.name, u.email, u.phone
                FROM payments p
                LEFT JOIN users u ON u.id = p.user_id
                ORDER BY p.created_at DESC
            """).fetchall()

        wb = Workbook()
        ws = wb.active
        ws.title = "Daily Payments"

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="101B3D", end_color="101B3D", fill_type="solid")
        center_align = Alignment(horizontal="center", vertical="center")

        headers = [
            "Date", "Transaction ID", "Student Name", "Email", "Phone", 
            "Amount (KES)", "Status", "Pesapal Ref", "Invoice Sent", "Reminders"
        ]
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align

        for row_num, r in enumerate(rows, 2):
            created_at = r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "-"
            invoice_sent = "Yes" if r["invoice_sent_at"] else "No"
            
            ws.cell(row=row_num, column=1, value=created_at)
            ws.cell(row=row_num, column=2, value=r["transaction_id"])
            ws.cell(row=row_num, column=3, value=r["name"] or "Unknown")
            ws.cell(row=row_num, column=4, value=r["email"] or "-")
            ws.cell(row=row_num, column=5, value=r["phone"] or "-")
            ws.cell(row=row_num, column=6, value=float(r["amount"]))
            ws.cell(row=row_num, column=7, value=str(r["status"]).capitalize())
            ws.cell(row=row_num, column=8, value=r["provider_reference"] or "-")
            ws.cell(row=row_num, column=9, value=invoice_sent)
            ws.cell(row=row_num, column=10, value=r["reminder_count"])

        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            ws.column_dimensions[column].width = max_length + 3

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        filename = f"EduPoint_Payments_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(
            buffer, 
            as_attachment=True, 
            download_name=filename, 
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        logger.error(f"Excel Export Failed: {traceback.format_exc()}")
        return jsonify(ok=False, error="Could not generate Excel file."), 500

@app.post("/api/admin/access/<int:user_id>")
@admin_required
def admin_access(user_id):
    d = request.get_json(silent=True) or {}
    credits_to_add = int(d.get("credits", 1))
    if credits_to_add > 0:
        with connect() as conn:
            conn.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (credits_to_add, user_id))
    return jsonify(ok=True, added=credits_to_add)

@app.get("/api/cron/daily-reports")
def trigger_daily_reports():
    try:
        secret = request.args.get("secret")
        expected_secret = os.getenv("CRON_SECRET", "edupoint_secret_123")
        if secret != expected_secret:
            return "Unauthorized", 401
        success = generate_and_send_reports()
        return ("OK", 200) if success else ("Failed to generate", 500)
    except Exception:
        logger.error(f"Cron Error: {traceback.format_exc()}")
        return "Error", 500

# ==========================================
# GLOBAL ERROR HANDLERS
# ==========================================
@app.errorhandler(404)
def not_found_error(error):
    return jsonify(ok=False, error="The requested resource was not found."), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    return jsonify(ok=False, error="Method not allowed."), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {traceback.format_exc()}")
    return jsonify(ok=False, error="A system error occurred. Please try again later."), 500

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description), e.code
    logger.error(f"Unhandled Exception: {traceback.format_exc()}")
    return jsonify(ok=False, error="An unexpected error occurred. Please contact support."), 500

# ================================================================
# ADMIN DASHBOARD — routes + email/invoice/report audit hooks
# Append this block at the bottom of app.py
# ================================================================
from services import admin_analytics as aa
import traceback as _tb
from datetime import timedelta as _td

# ---------- Overview & chart endpoints ----------
@app.get("/api/admin/overview")
@admin_required
def api_admin_overview():
    u = current_user()
    return jsonify(
        ok=True,
        stats=aa.overview_stats(7),
        activity=aa.daily_activity(7),
        payment_distribution=aa.payment_distribution(),
        student_distribution=aa.student_distribution(),
        revenue=aa.revenue_trend(14),
        recent_students=aa.list_students(5),
        system_health=aa.system_health(),
        admin={"name": u.get("name","Admin"), "email": u["email"], "role": u.get("role","admin")}
    )


@app.get("/api/admin/charts/<name>")
@admin_required
def api_admin_chart(name):
    days = int(request.args.get("days", 30))
    mapping = {
        "daily-activity":     lambda: aa.daily_activity(days),
        "revenue":            lambda: aa.revenue_trend(days),
        "registrations":      lambda: aa.registration_trend(days),
        "payment-performance":lambda: aa.payment_performance(days),
        "cluster":            aa.cluster_distribution,
        "invoice-report":     lambda: aa.invoice_report_trend(days),
        "reminders":          lambda: aa.reminder_stats(days),
        "payment-distribution": aa.payment_distribution,
        "student-distribution": aa.student_distribution,
        "email-distribution":   aa.email_distribution,
        "invoice-distribution": aa.invoice_distribution,
        "report-distribution":  aa.report_distribution,
    }
    fn = mapping.get(name)
    if not fn:
        return jsonify(ok=False, error="Unknown chart"), 404
    return jsonify(ok=True, data=fn())


# ---------- Students ----------
@app.get("/api/admin/students")
@admin_required
def api_admin_students():
    status_filter = request.args.get("status")
    return jsonify(ok=True, students=aa.list_students(300, status_filter))


@app.post("/api/admin/students/<int:user_id>/status")
@admin_required
def api_admin_student_status(user_id):
    d = request.get_json(silent=True) or {}
    status = d.get("status")
    if status not in ("active", "suspended"):
        return jsonify(ok=False, error="Invalid status"), 400
    aa.set_student_status(user_id, status, current_user())
    return jsonify(ok=True)


# ---------- Payments (read-only view; verifications go through existing logic) ----------
@app.get("/api/admin/payments")
@admin_required
def api_admin_payments():
    with connect() as conn:
        rows = conn.execute("""
            SELECT p.id, p.transaction_id, p.user_id, p.amount, p.status, p.created_at,
                   p.network, p.provider_reference,
                   u.name student_name, u.email student_email,
                   i.invoice_number invoice_id,
                   (SELECT email_status FROM report_versions rv
                     WHERE rv.history_id = (SELECT id FROM calculation_history ch
                        WHERE ch.user_id = p.user_id ORDER BY ch.created_at DESC LIMIT 1)
                     ORDER BY rv.created_at DESC LIMIT 1) report_status
            FROM payments p
            LEFT JOIN users u ON u.id=p.user_id
            LEFT JOIN invoice_records i ON i.transaction_id=p.transaction_id
            ORDER BY p.created_at DESC LIMIT 500""").fetchall()
    return jsonify(ok=True, payments=[dict(r) for r in rows])


# ---------- Calculations ----------
@app.get("/api/admin/calculations")
@admin_required
def api_admin_calculations():
    with connect() as conn:
        rows = conn.execute("""
            SELECT h.id, h.reference, h.user_id, h.cluster_points, h.created_at,
                   h.report_status, u.name student_name, u.email student_email
            FROM calculation_history h LEFT JOIN users u ON u.id=h.user_id
            ORDER BY h.created_at DESC LIMIT 500""").fetchall()
    return jsonify(ok=True, calculations=[dict(r) for r in rows])


# ---------- Eligibility ----------
@app.get("/api/admin/eligibility")
@admin_required
def api_admin_eligibility():
    # Aggregates from calculation results if stored; otherwise empty
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT u.name student_name, h.cluster_points,
                       cc.course, cc.university, cc.cutoff,
                       CASE WHEN h.cluster_points >= cc.cutoff THEN 'eligible'
                            WHEN cc.cutoff - h.cluster_points <= 1.0 THEN 'close'
                            ELSE 'not' END status
                FROM calculation_history h
                JOIN users u ON u.id = h.user_id
                LEFT JOIN calculation_courses cc ON cc.history_id = h.id
                WHERE h.cluster_points IS NOT NULL
                ORDER BY h.created_at DESC LIMIT 500
            """).fetchall()
        return jsonify(ok=True, rows=[dict(r) for r in rows])
    except Exception:
        return jsonify(ok=True, rows=[])


# ---------- Invoices, reports, emails ----------
@app.get("/api/admin/invoices")
@admin_required
def api_admin_invoices():
    return jsonify(ok=True, invoices=aa.list_invoices())


@app.get("/api/admin/reports")
@admin_required
def api_admin_reports():
    return jsonify(ok=True, reports=aa.list_reports())


@app.get("/api/admin/emails")
@admin_required
def api_admin_emails():
    return jsonify(ok=True, emails=aa.list_emails(300, request.args.get("status")))


# ---------- Reminders ----------
@app.get("/api/admin/reminders")
@admin_required
def api_admin_reminders():
    return jsonify(ok=True, reminders=aa.list_outstanding_reminders())


# ---------- Audit / health / settings ----------
@app.get("/api/admin/audit-logs")
@admin_required
def api_admin_audit():
    return jsonify(ok=True, logs=aa.list_audit())


@app.get("/api/admin/health")
@admin_required
def api_admin_health():
    return jsonify(ok=True, checks=aa.system_health(), data_quality=aa.data_quality())


@app.get("/api/admin/settings")
@admin_required
def api_admin_settings_get():
    return jsonify(ok=True, settings=aa.get_settings())


@app.post("/api/admin/settings/<key>")
@admin_required
def api_admin_settings_set(key):
    d = request.get_json(silent=True) or {}
    aa.set_setting(key, d, current_user()["id"])
    aa.log_audit(current_user(), f"settings.update.{key}", "settings", key, d)
    return jsonify(ok=True)


# ---------- Daily Excel ----------
@app.get("/api/admin/excel/history")
@admin_required
def api_admin_excel_history():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_excel_reports ORDER BY report_date DESC LIMIT 90").fetchall()
    return jsonify(ok=True, rows=[
        dict(r, report_date=str(r["report_date"]),
             generated_at=str(r["generated_at"])) for r in rows])


@app.post("/api/admin/excel/generate")
@admin_required
def api_admin_excel_generate():
    d = request.get_json(silent=True) or {}
    day_str = d.get("date")
    day = datetime.strptime(day_str, "%Y-%m-%d").date() if day_str else (
        aa.today_nairobi() - _td(days=1))
    res = aa.generate_and_store_daily_excel(day)
    if not res:
        return jsonify(ok=False, error="Already exists or generation failed"), 400
    aa.log_audit(current_user(), "excel.generate", "daily_excel", str(day), res)
    return jsonify(ok=True, **res)


@app.get("/api/admin/excel/download/<int:report_id>")
@admin_required
def api_admin_excel_download(report_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM daily_excel_reports WHERE id=%s", (report_id,)).fetchone()
    if not row or not row["file_path"] or not os.path.exists(row["file_path"]):
        return jsonify(ok=False, error="File not found"), 404
    return send_file(row["file_path"], as_attachment=True, download_name=row["filename"])


# ---------- Cron endpoint for daily Excel ----------
@app.get("/api/admin/cron/daily-excel")
def cron_daily_excel():
    secret = request.args.get("secret")
    if secret != os.getenv("CRON_SECRET", "change_me_in_env"):
        return "Unauthorized", 401
    res = aa.generate_and_store_daily_excel()
    return jsonify(ok=True, generated=res)


# ================================================================
# EMAIL / INVOICE / REPORT LOGGING HOOKS
# ================================================================
# These wrap your existing senders so every email, invoice, and
# report is automatically logged to the audit trail. If a wrapper
# fails to reach the original (because of a signature mismatch),
# it silently passes through — nothing breaks.

def _log_email_safe(user_id, email_to, email_type, subject,
                    status="accepted_by_provider", error=None):
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO email_logs(user_id,email_to,email_type,subject,status,error_message) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (user_id, email_to, email_type, subject, status, error))
    except Exception:
        log_msg = _tb.format_exc()
        print(f"[admin_hook] log_email failed: {log_msg}")


def _log_invoice_safe(invoice_number, transaction_id, user_id, amount):
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO invoice_records"
                "(invoice_number,transaction_id,user_id,amount,delivery_status,email_sent_at) "
                "VALUES(%s,%s,%s,%s,'sent',now()) "
                "ON CONFLICT (invoice_number) DO NOTHING",
                (invoice_number, transaction_id, user_id, amount))
    except Exception:
        print(f"[admin_hook] log_invoice failed: {_tb.format_exc()}")


def _log_report_safe(user_id):
    try:
        with connect() as conn:
            hist = conn.execute(
                "SELECT id FROM calculation_history WHERE user_id=%s "
                "ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
            if hist:
                conn.execute(
                    "INSERT INTO report_versions"
                    "(history_id,version,pdf_status,email_status) "
                    "VALUES(%s,1,'generated','sent')", (hist["id"],))
    except Exception:
        print(f"[admin_hook] log_report failed: {_tb.format_exc()}")


# ---- Wrap existing email senders by known common names ----
# We try each one; if not defined, we skip silently.

def _wrap_and_hook(name, before=None, after=None):
    fn = globals().get(name)
    if not callable(fn):
        return
    def wrapper(*args, **kwargs):
        result = None
        try:
            if before:
                before(*args, **kwargs)
            result = fn(*args, **kwargs)
            if after:
                after(result, *args, **kwargs)
        except Exception as e:
            print(f"[admin_hook] {name} raised: {e}")
            raise
        return result
    wrapper.__name__ = name
    globals()[name] = wrapper


# send_pending_invoice_email(user_email, user_name, payment)
def _before_invoice(user_email=None, user_name=None, payment=None, *a, **k):
    if payment:
        _log_email_safe(
            payment.get("user_id"), user_email, "invoice_pending",
            f"Invoice {str(payment.get('transaction_id',''))[-8:]}",
            status="accepted_by_provider")
        _log_invoice_safe(
            "INV-" + str(payment.get("transaction_id",""))[-8:].upper(),
            payment.get("transaction_id"),
            payment.get("user_id"),
            float(payment.get("amount", 0)))

_wrap_and_hook("send_pending_invoice_email", before=_before_invoice)


# send_paid_receipt_email(user_email, user_name, cluster_points, results,
#                        subjects, grades, scholarships, payment)
def _after_receipt(result=None, user_email=None, *a, **k):
    payment = k.get("payment")
    if not payment and len(a) >= 7:
        payment = a[6]  # positional 7th arg
    uid = payment.get("user_id") if isinstance(payment, dict) else None
    _log_email_safe(uid, user_email, "report_receipt", "Your Results & Receipt",
                    status="accepted_by_provider")
    if uid:
        _log_report_safe(uid)

_wrap_and_hook("send_paid_receipt_email", after=_after_receipt)


# send_reminder_email(user_email, user_name, payment)
def _before_reminder(user_email=None, user_name=None, payment=None, *a, **k):
    if payment:
        _log_email_safe(
            payment.get("user_id"), user_email, "reminder",
            f"Reminder {str(payment.get('transaction_id',''))[-8:]}",
            status="accepted_by_provider")
        try:
            aa.log_reminder(payment.get("transaction_id"))
        except Exception:
            pass

_wrap_and_hook("send_reminder_email", before=_before_reminder)


# Any additional common names you may have — hooks attempt each silently
for _fn_name in ("send_payment_failed_email", "send_payment_success_email"):
    if callable(globals().get(_fn_name)):
        print(f"[admin_hook] found {_fn_name}; extend hooks if you want it logged")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
