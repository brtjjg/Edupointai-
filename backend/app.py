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
# ATOMIC CLAIM + PROCESS (pay-per-calculation)
# ==========================================
#
# This is the ONLY code path that ever computes results.
# It requires a payment row with status='paid', and atomically flips it to
# 'completed' so no double-processing is possible. If a webhook and the frontend
# race, only one wins. Results are then persisted to results_json so the loser
# can still return them without recomputing.
#
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
        logger.warning(f"Claimed {tx_id} but no calc_data")
        return None

    with connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE id = %s", (row["user_id"],)).fetchone()

    try:
        calc_results = process_calculation(u, calc_data["subjects"], calc_data["grades"])

        # Persist results so the webhook-first / polling race doesn't lose them
        with connect() as conn:
            conn.execute(
                "UPDATE payments SET results_json = %s WHERE transaction_id = %s",
                (json.dumps(calc_results), tx_id)
            )

        send_paid_receipt_email(
            u["email"], u["name"],
            calc_results["cluster_points"], calc_results["results"],
            calc_data["subjects"], calc_data["grades"],
            SCHOLARSHIPS, row
        )
        logger.info(f"Processed {tx_id} and emailed results to {u['email']}")
        return calc_results
    except Exception as e:
        with connect() as conn:
            conn.execute("UPDATE payments SET status = 'paid' WHERE transaction_id = %s", (tx_id,))
        logger.error(f"Claim+process failed for {tx_id}: {traceback.format_exc()}")
        return None


# ==========================================
# PDF GENERATION
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


def send_invoice_email(user_email, user_name, payment):
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

        pay_button_html = ""
        if pay_link:
            pay_button_html = f"""
            <p style="text-align:center;margin:32px 0;">
              <a href="{pay_link}"
                 style="display:inline-block;background:#2563EB;color:#ffffff;padding:16px 52px;
                        text-decoration:none;border-radius:10px;font-weight:bold;font-size:16px;">
                💳 PAY NOW — KES {amount:.0f}
              </a>
            </p>
            <p style="text-align:center;font-size:12px;color:#64748B;">
              You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, T-Kash, or Card.
            </p>
            """

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;line-height:1.6;color:#1F2937;">
          <h2>Hi {user_name},</h2>
          <p>Thank you for using <b>EduPointAI</b>! Your invoice is attached below.</p>
          <div style="background:#F4F6FC;padding:16px;border-radius:8px;margin:20px 0;">
            <p style="margin:0;"><b>Invoice:</b> INV-{inv_short}</p>
            <p style="margin:6px 0 0;"><b>Amount:</b> KES {amount:.2f}</p>
            <p style="margin:6px 0 0;"><b>Status:</b> Awaiting Payment</p>
          </div>
          <p>Complete the payment to unlock your <b>Comprehensive Results Report</b>:
            all 200+ courses, their subject requirements, cutoffs, and scholarship opportunities.</p>
          {pay_button_html}
          <p style="font-size:13px;color:#64748B;">
            Once paid you'll be returned to the EduPointAI website and your report will arrive by email.
            We'll send a friendly reminder every 24 hours until your invoice is settled.
          </p>
          <p>Best regards,<br/><b>EduPointAI Team</b></p>
        </div>
        """

        client.transactional_emails.send_transac_email(
            subject=f"EduPointAI Invoice {inv_short} — KES {amount:.0f}",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"}],
        )
        logger.info(f"Sent invoice with Pay Now to {user_email}")
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
        <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;line-height:1.6;color:#1F2937;">
          <h2>Hi {user_name},</h2>
          <p>This is a friendly reminder — your <b>EduPointAI invoice is still awaiting payment</b>.</p>
          <div style="background:#FEF6E0;border-left:4px solid #F59E0B;padding:16px;border-radius:4px;margin:22px 0;">
            <p style="margin:0;"><b>Invoice:</b> INV-{inv_short}</p>
            <p style="margin:6px 0 0;"><b>Amount Due:</b> KES {amount:.2f}</p>
            <p style="margin:6px 0 0;"><b>Reminder:</b> #{reminder_num}</p>
          </div>
          <p style="text-align:center;margin:32px 0;">
            <a href="{pay_link}"
               style="display:inline-block;background:#2563EB;color:#ffffff;padding:16px 52px;
                      text-decoration:none;border-radius:10px;font-weight:bold;font-size:16px;">
              💳 PAY NOW — KES {amount:.0f}
            </a>
          </p>
          <p style="text-align:center;font-size:12px;color:#64748B;">
            You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, T-Kash, or Card.
          </p>
          <p style="font-size:13px;color:#64748B;">
            If you have already paid, please ignore this email — your Results Report will arrive shortly.
          </p>
          <p>Best regards,<br/><b>EduPointAI Team</b></p>
        </div>
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

        html = (
            f"<div style='font-family: Arial; line-height: 1.6;'>"
            f"<h2>Dear {user_name},</h2>"
            f"<p>Your payment is confirmed and your comprehensive academic report is ready.</p>"
            f"<p><b>Cluster Points:</b> {cluster_points}</p>"
            f"<p>Your attached <b>Comprehensive Results Report</b> includes:</p>"
            f"<ul>"
            f"<li><b>Every course</b> in our database (200+)</li>"
            f"<li>Courses grouped by: <b>Qualified</b> • <b>Close (±2 points)</b> • <b>Not Yet Qualified</b></li>"
            f"<li>The <b>specific subjects each course requires</b></li>"
            f"<li>Cutoffs, duration and how far you are from each course</li>"
            f"</ul>"
            f"<p>You will also find your <b>Payment Receipt</b> attached.</p>"
            f"<p>EduPointAI Team</p>"
            f"</div>"
        )
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
def health(): return jsonify(ok=True, service="edupoint-api")

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
    return jsonify(ok=True, user=public_user(u), credits=u.get("credits", 0))

# ==========================================
# PAYMENT: every call creates a NEW Pesapal order + invoice (pay-per-calculation)
# ==========================================
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
            target=send_invoice_email,
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

    # Poll Pesapal if still pending
    if row["status"] == "pending":
        try:
            rr = payments.check_status(row)
            if rr:
                payments.update(transaction_id, status=rr["status"], message=rr.get("message"))
                row = payments.get(transaction_id)
        except Exception:
            logger.exception("Status check failed")

    # If the payment has just become 'paid', try to claim & process.
    if row["status"] == "paid":
        _claim_and_process(transaction_id)
        row = payments.get(transaction_id)

    # Return stored results (whether we just processed them or webhook already did).
    calc_results = None
    if row["status"] == "completed" and row.get("results_json"):
        calc_results = row["results_json"]

    return jsonify(ok=True, payment=row, calculation_results=calc_results)


@app.get("/api/cron/send-reminders")
def trigger_reminders():
    secret = request.args.get("secret")
    expected = os.getenv("CRON_SECRET", "edupoint_secret_123")
    if secret != expected:
        return "Unauthorized", 401

    # 1. Retry any stuck 'paid' payments (webhook ran but processing crashed)
    with connect() as conn:
        stuck = conn.execute("""
            SELECT transaction_id FROM payments 
            WHERE status = 'paid' AND updated_at < now() - INTERVAL '5 minutes'
            LIMIT 20
        """).fetchall()
    for s in stuck:
        _claim_and_process(s["transaction_id"])

    # 2. Send daily reminders
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

@app.get("/api/admin/users")
@admin_required
def admin_users():
    with connect() as conn:
        rows = conn.execute("SELECT id,name,email,phone,role,active,credits FROM users ORDER BY id DESC").fetchall()
    return jsonify(ok=True, users=[dict(r) for r in rows])

@app.get("/api/admin/payments")
@admin_required
def admin_payments():
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, transaction_id, user_id, amount, status,
                   invoice_sent_at, last_reminder_at, reminder_count
            FROM payments ORDER BY id DESC LIMIT 100
        """).fetchall()
    return jsonify(ok=True, payments=[dict(r) for r in rows])


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
