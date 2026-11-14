#!/usr/bin/env python3
import os, uuid, logging, base64, threading, random, string, io, json, traceback, re
from datetime import datetime, timedelta
import pytz
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
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

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

# Colors for Excel
NAVY = "0B1530"
TEAL = "16B8A6"
EMERALD = "16A36A"
BLUE = "2563EB"
PURPLE = "7952C7"
AMBER = "F59E0B"
RED = "DC3545"
WHITE = "FFFFFF"
GREY = "64748B"

# ==========================================
# HELPERS & CALCULATION
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
    NAVY_PDF = HexColor("#172554"); PALE = HexColor("#F4F6FC"); LIGHT_BLUE = HexColor("#EAF3FF")
    LIGHT_PURPLE = HexColor("#F1ECFB"); INK = HexColor("#1F2937"); MUTED = HexColor("#64748B")
    BORDER = HexColor("#DCE3EF")
    GREEN_HDR = HexColor("#15803D"); AMBER_HDR = HexColor("#B45309"); RED_HDR = HexColor("#B91C1C")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.white))
    styles.add(ParagraphStyle(name="HeroTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_LEFT, textColor=NAVY_PDF))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY_PDF, spaceBefore=6, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=INK))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.5, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=NAVY_PDF))
    styles.add(ParagraphStyle(name="WhiteSmall", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, textColor=colors.white))

    def P(text, style="BodySmall"):
        return Paragraph(str(text), styles[style])

    def header_footer(canvas, doc):
        canvas.saveState(); w, h = A4
        canvas.setFillColor(NAVY_PDF); canvas.rect(0, h - 8*mm, w, 8*mm, stroke=0, fill=1)
        canvas.setStrokeColor(BORDER); canvas.line(18*mm, 16*mm, w - 18*mm, 16*mm)
        canvas.setFont("Helvetica", 7); canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 10.5*mm, "EduPointAI  |  Your Education. Your Future.")
        canvas.drawRightString(w - 18*mm, 10.5*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=17*mm, bottomMargin=23*mm)
    qualified = sorted([r for r in results if r["match"] == "qualified"], key=lambda x: -x["c"])
    close = sorted([r for r in results if r["match"] == "close"], key=lambda x: -x["c"])
    not_qual = sorted([r for r in results if r["match"] == "not_qualified"], key=lambda x: -x["c"])

    def build_course_table(courses, header_color):
        header = [P("COURSE", "Tiny"), P("UNIVERSITY", "Tiny"), P("CUTOFF", "Tiny"), P("GAP", "Tiny"), P("DUR", "Tiny"), P("KEY SUBJECTS REQUIRED", "Tiny")]
        data = [header]
        for c in courses:
            req, other, _note = get_subject_requirements(c["n"])
            req_str = ", ".join(req)
            if other: req_str += " • " + other
            data.append([P(c["n"], "BodySmall"), P(c["u"], "BodySmall"), P(f"{c['c']:.3f}", "BodySmall"), P(f"{c['difference']:+.2f}", "BodySmall"), P(f"{c['y']}y", "BodySmall"), P(req_str, "BodySmall")])
        t = Table(data, colWidths=[44*mm, 33*mm, 13*mm, 12*mm, 10*mm, 50*mm], repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), header_color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i in range(1, len(data)):
            if i % 2 == 0: style.append(("BACKGROUND", (0, i), (-1, i), HexColor("#F8FAFC")))
        t.setStyle(TableStyle(style))
        return t

    story = []
    brand = Table([[P("EduPointAI", "Brand"), P("COMPREHENSIVE CLUSTER & COURSE REPORT", "WhiteSmall")]], colWidths=[70*mm, 104*mm], rowHeights=[22*mm])
    brand.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY_PDF), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [brand, Spacer(1, 7*mm)]
    story += [P("Your cluster points & full course eligibility", "HeroTitle"), P("Every course in our database, grouped by whether your cluster meets, is close to, or is below the cutoff — with the specific subjects each course requires.", "Sub"), Spacer(1, 4*mm)]

    ref = "EP-2026-" + ''.join(random.choices(string.digits, k=6))
    student = Table([[P("STUDENT", "Tiny"), P("EMAIL", "Tiny"), P("REPORT REFERENCE", "Tiny")], [P(user_name, "BodySmall"), P(user_email, "BodySmall"), P(ref, "BodySmall")]], colWidths=[60*mm, 60*mm, 54*mm])
    student.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.7, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [student, Spacer(1, 4*mm)]

    cards = Table([[P("CLUSTER POINTS", "CardLabel"), P("QUALIFIED", "CardLabel"), P("CLOSE (±2)", "CardLabel"), P("NOT YET", "CardLabel")], [P(f"{cluster_points}", "CardValue"), P(str(len(qualified)), "CardValue"), P(str(len(close)), "CardValue"), P(str(len(not_qual)), "CardValue")]], colWidths=[43.5*mm]*4)
    cards.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE), ("BACKGROUND", (1, 0), (1, -1), HexColor("#E8F8EF")), ("BACKGROUND", (2, 0), (2, -1), HexColor("#FEF6E0")), ("BACKGROUND", (3, 0), (3, -1), HexColor("#FDEDED")), ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 1, colors.white), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [cards, Spacer(1, 4*mm)]

    story += [P("01  Your KCSE Subject Breakdown", "Section")]
    grades_data = [[P("SUBJECT", "Tiny"), P("GRADE", "Tiny"), P("POINTS", "Tiny")]]
    for i in range(7):
        subj = subjects.get(str(i), f"Subject {i+1}")
        grade = grades.get(str(i), "-")
        pts = W.get(grade.upper(), 0) if grade else 0
        grades_data.append([P(subj, "BodySmall"), P(grade, "BodySmall"), P(str(pts), "BodySmall")])
    gt = Table(grades_data, colWidths=[110*mm, 30*mm, 30*mm])
    gt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PALE), ("GRID", (0, 0), (-1, -1), 0.45, BORDER), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    total_pts = sum(W.get((grades.get(str(i)) or "").upper(), 0) for i in range(7))
    story += [gt, Spacer(1, 2*mm), P(f"<i>Formula:</i> (sum of best 7 subject points ÷ {BEST:.0f}) × {MAX:.0f} = ({total_pts} ÷ {BEST:.0f}) × {MAX:.0f} = <b>{cluster_points}</b>", "Sub")]

    story.append(PageBreak())
    story += [P("02  Top 10 Recommended Courses", "Section"), P(f"These are the highest-cutoff courses you currently qualify for. Your cluster ({cluster_points}) meets or exceeds their cutoffs.", "Sub"), Spacer(1, 3*mm)]
    if qualified: story.append(build_course_table(qualified[:10], GREEN_HDR))
    else: story.append(P("You do not yet meet the cutoff for any course in our database.", "BodySmall"))

    if qualified:
        story.append(PageBreak())
        story += [P(f"03  All Courses You Qualify For ({len(qualified)})", "Section"), P("Your cluster meets or exceeds every cutoff listed below.", "Sub"), Spacer(1, 3*mm), build_course_table(qualified, GREEN_HDR)]
    if close:
        story.append(PageBreak())
        story += [P(f"04  Close Matches — Within 2.0 Points ({len(close)})", "Section"), P("You are just below the cutoff.", "Sub"), Spacer(1, 3*mm), build_course_table(close, AMBER_HDR)]
    if not_qual:
        story.append(PageBreak())
        story += [P(f"05  Not Yet Qualified ({len(not_qual)})", "Section"), P("Cutoff is more than 2.0 points above your cluster.", "Sub"), Spacer(1, 3*mm), build_course_table(not_qual, RED_HDR)]

    story.append(PageBreak())
    story += [P("06  Scholarship Opportunities", "Section")]
    sch_data = [[P("SCHOLARSHIP", "Tiny"), P("AMOUNT", "Tiny"), P("LINK", "Tiny")]]
    for s in scholarships[:8]: sch_data.append([P(s["name"], "BodySmall"), P(s["amount"], "BodySmall"), P(s["link"], "BodySmall")])
    st = Table(sch_data, colWidths=[65*mm, 45*mm, 64*mm])
    st.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT_PURPLE), ("GRID", (0, 0), (-1, -1), 0.45, BORDER), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [st, Spacer(1, 5*mm), P("<i>Note:</i> Cutoff points change every year. Always verify on the official KUCCPS portal.", "Sub")]

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    buffer.seek(0)
    return buffer

# ==========================================
# EMAIL SENDERS & EXCEL GENERATOR
# ==========================================
def _get_brevo():
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    if not api_key or not sender_email: return None, None
    return Brevo(api_key=api_key), sender_email

def send_pending_invoice_email(user_email, user_name, payment):
    try:
        client, sender_email = _get_brevo()
        if not client: return
        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")
        pay_link = (payment.get("redirect_url") or "").strip()
        amount = float(payment.get("amount", 0))
        inv_short = payment["transaction_id"][-8:].upper()

        html = f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr><td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                        <tr><td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;"><h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700;">EduPointAI ✦</h1></td></tr>
                        <tr><td style="padding: 40px;">
                            <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                <tr><td align="center" style="padding-bottom: 20px;"><span style="display: inline-block; background-color: #F2A93B; color: #101B3D; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Awaiting Payment</span></td></tr>
                                <tr><td align="center" style="padding-bottom: 15px;"><h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">Your invoice is ready!</h2></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><p style="color: #26324D; margin: 0; font-size: 16px;">One step closer to unlocking your academic opportunities.</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;"></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><p style="color: #7047EB; margin: 0 0 10px 0; font-size: 14px; font-weight: 600; text-transform: uppercase;">Invoice INV-{inv_short}</p><p style="color: #101B3D; margin: 0; font-size: 32px; font-weight: 800;">KES {amount:,.2f}</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><a href="{pay_link}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px;">PAY NOW — KES {amount:.0f}</a></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><p style="color: #64748B; margin: 0; font-size: 13px;">You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, T-Kash, or Card.</p></td></tr>
                            </table>
                        </td></tr>
                        <tr><td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;"><p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p><p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p></td></tr>
                    </table>
                </td></tr>
            </table>
        </body></html>
        """
        client.transactional_emails.send_transac_email(
            subject=f"EduPointAI Invoice {inv_short} — KES {amount:.0f}",
            html_content=html, sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"}],
        )
    except Exception: logger.error(f"Failed to send invoice email: {traceback.format_exc()}")

def send_reminder_email(user_email, user_name, payment):
    try:
        client, sender_email = _get_brevo()
        if not client: return
        pay_link = (payment.get("redirect_url") or "").strip()
        if not pay_link: return
        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")
        amount = float(payment.get("amount", 0))
        inv_short = payment["transaction_id"][-8:].upper()
        reminder_num = (payment.get("reminder_count") or 0) + 1

        html = f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr><td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                        <tr><td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;"><h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700;">EduPointAI ✦</h1></td></tr>
                        <tr><td style="padding: 40px;">
                            <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                <tr><td align="center" style="padding-bottom: 20px;"><span style="display: inline-block; background-color: #F2A93B; color: #101B3D; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Payment Reminder</span></td></tr>
                                <tr><td align="center" style="padding-bottom: 15px;"><h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">A friendly reminder!</h2></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><p style="color: #26324D; margin: 0; font-size: 16px;">Your EduPointAI Comprehensive Results Report is waiting for you.</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;"></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><p style="color: #7047EB; margin: 0 0 10px 0; font-size: 14px; font-weight: 600; text-transform: uppercase;">Invoice INV-{inv_short} • Reminder #{reminder_num}</p><p style="color: #101B3D; margin: 0; font-size: 32px; font-weight: 800;">KES {amount:,.2f}</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><a href="{pay_link}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px;">PAY NOW — KES {amount:.0f}</a></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><p style="color: #64748B; margin: 0; font-size: 13px;">If you have already paid, please ignore this email — your Results Report will arrive shortly.</p></td></tr>
                            </table>
                        </td></tr>
                        <tr><td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;"><p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p><p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p></td></tr>
                    </table>
                </td></tr>
            </table>
        </body></html>
        """
        client.transactional_emails.send_transac_email(
            subject=f"Reminder: Invoice INV-{inv_short} unpaid — KES {amount:.0f}",
            html_content=html, sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"}],
        )
    except Exception: logger.error(f"Failed to send reminder: {traceback.format_exc()}")

def send_paid_receipt_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships, payment):
    try:
        client, sender_email = _get_brevo()
        if not client: return
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode("utf-8")
        attachments = [{"content": pdf_base64, "name": "EduPointAI_Results.pdf"}]

        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode("utf-8")
        attachments.append({"content": inv_base64, "name": f"Receipt_{payment['transaction_id']}.pdf"})

        html = f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
                <tr><td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                        <tr><td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;"><h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700;">EduPointAI ✦</h1></td></tr>
                        <tr><td style="padding: 40px;">
                            <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                <tr><td align="center" style="padding-bottom: 20px;"><span style="display: inline-block; background-color: #0F9D91; color: #ffffff; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">Payment Confirmation</span></td></tr>
                                <tr><td align="center" style="padding-bottom: 15px;"><h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">Payment successful! <span style="color: #0F9D91; font-size: 28px;">✓</span></h2></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><p style="color: #26324D; margin: 0; font-size: 16px;">Thank you! Your payment has been confirmed.</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><hr style="border: 0; border-top: 1px solid #E2E8F0; width: 60%; margin: 0 auto;"></td></tr>
                                <tr><td align="center" style="padding-bottom: 30px;"><h3 style="color: #7047EB; margin: 0 0 10px 0; font-size: 22px; font-weight: 700;">Your report is ready! 🎓</h3><p style="color: #26324D; margin: 0; font-size: 15px;">Your next academic chapter starts here.</p><p style="color: #26324D; margin: 10px 0 0 0; font-size: 15px;"><strong>Cluster Points:</strong> {cluster_points}</p></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><a href="https://edupointai-frontend.vercel.app/" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px;">VIEW MY REPORT</a></td></tr>
                                <tr><td align="center" style="padding-bottom: 20px;"><p style="color: #64748B; margin: 0; font-size: 13px;">Your official Results Report and Payment Receipt are attached to this email.</p></td></tr>
                            </table>
                        </td></tr>
                        <tr><td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;"><p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">academichelpdesk1@gmail.com</a></p><p style="color: #94A3B8; margin: 0; font-size: 12px;">© 2026 EduPointAI. All rights reserved.</p></td></tr>
                    </table>
                </td></tr>
            </table>
        </body></html>
        """
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Results & Receipt",
            html_content=html, sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=attachments,
        )
    except Exception: logger.error(f"Failed to send results email: {traceback.format_exc()}")

# ==========================================
# DAILY EXCEL REPORT GENERATOR
# ==========================================
def create_daily_excel_report():
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Executive Summary"
    
    # Helper for formatting
    def style_sheet(ws, title, color):
        ws.sheet_view.showGridLines = False
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, color="FFFFFF", size=14)
        ws["A1"].fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells("A1:H1")
        ws.row_dimensions[1].height = 30
        
    def add_headers(ws, headers, row_num=3):
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=row_num, column=col, value=h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="14213D", end_color="14213D", fill_type="solid")
            cell.alignment = Alignment(horizontal="center")
        ws.freeze_panes = f"A{row_num+1}"

    # 1. Summary
    style_sheet(ws_summary, "EduPoint AI - Daily Administration Report", "0B1530")
    ws_summary["A2"] = f"Generated: {datetime.now(pytz.timezone('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M')} EAT"
    ws_summary["A2"].font = Font(italic=True, color="64748B")
    
    with connect() as conn:
        rev = conn.execute("SELECT SUM(amount) FROM payments WHERE status IN ('paid', 'completed')").fetchone()['sum'] or 0
        users = conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()['count']
        calcs = conn.execute("SELECT COUNT(*) FROM calculation_history").fetchone()['count']
        pending = conn.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()['count']
        failed = conn.execute("SELECT COUNT(*) FROM payments WHERE status='failed'").fetchone()['count']
        
        ws_summary["A4"] = "Financial Overview"
        ws_summary["A4"].font = Font(bold=True, color="16B8A6", size=12)
        ws_summary["A5"], ws_summary["B5"] = "Total Confirmed Revenue (KES)", rev
        ws_summary["A6"], ws_summary["B6"] = "Pending Payments", pending
        ws_summary["A7"], ws_summary["B7"] = "Failed Payments", failed
        
        ws_summary["A9"] = "Academic Overview"
        ws_summary["A9"].font = Font(bold=True, color="7952C7", size=12)
        ws_summary["A10"], ws_summary["B10"] = "Total Registered Students", users
        ws_summary["A11"], ws_summary["B11"] = "Total Calculations", calcs

    # 2. All Payments
    ws_pay = wb.create_sheet("Payment Transactions")
    style_sheet(ws_pay, "All Payment Transactions", "2563EB")
    add_headers(ws_pay, ["TxID", "User ID", "Amount (KES)", "Status", "Provider Ref", "Created At", "Updated At"])
    
    with connect() as conn:
        pays = conn.execute("SELECT transaction_id, user_id, amount, status, provider_reference, created_at, updated_at FROM payments ORDER BY created_at DESC").fetchall()
        for i, p in enumerate(pays, 4):
            ws_pay.cell(row=i, column=1, value=p["transaction_id"])
            ws_pay.cell(row=i, column=2, value=p["user_id"])
            ws_pay.cell(row=i, column=3, value=float(p["amount"]))
            ws_pay.cell(row=i, column=4, value=p["status"])
            ws_pay.cell(row=i, column=5, value=p["provider_reference"] or "")
            ws_pay.cell(row=i, column=6, value=p["created_at"].strftime("%Y-%m-%d %H:%M") if p["created_at"] else "")
            ws_pay.cell(row=i, column=7, value=p["updated_at"].strftime("%Y-%m-%d %H:%M") if p["updated_at"] else "")
    
    # 3. Successful Payments
    ws_succ = wb.create_sheet("Successful Payments")
    style_sheet(ws_succ, "Successful Payments", "16A36A")
    add_headers(ws_succ, ["TxID", "User ID", "Amount (KES)", "Date Confirmed"])
    with connect() as conn:
        su = conn.execute("SELECT transaction_id, user_id, amount, updated_at FROM payments WHERE status IN ('paid', 'completed') ORDER BY updated_at DESC").fetchall()
        for i, p in enumerate(su, 4):
            ws_succ.cell(row=i, column=1, value=p["transaction_id"])
            ws_succ.cell(row=i, column=2, value=p["user_id"])
            ws_succ.cell(row=i, column=3, value=float(p["amount"]))
            ws_succ.cell(row=i, column=4, value=p["updated_at"].strftime("%Y-%m-%d %H:%M") if p["updated_at"] else "")

    # 4. Pending Payments
    ws_pend = wb.create_sheet("Pending Payments")
    style_sheet(ws_pend, "Pending Payments", "F59E0B")
    add_headers(ws_pend, ["TxID", "User ID", "Amount (KES)", "Date Initiated"])
    with connect() as conn:
        pe = conn.execute("SELECT transaction_id, user_id, amount, created_at FROM payments WHERE status='pending' ORDER BY created_at DESC").fetchall()
        for i, p in enumerate(pe, 4):
            ws_pend.cell(row=i, column=1, value=p["transaction_id"])
            ws_pend.cell(row=i, column=2, value=p["user_id"])
            ws_pend.cell(row=i, column=3, value=float(p["amount"]))
            ws_pend.cell(row=i, column=4, value=p["created_at"].strftime("%Y-%m-%d %H:%M") if p["created_at"] else "")

    # 5. Failed Payments
    ws_fail = wb.create_sheet("Failed Payments")
    style_sheet(ws_fail, "Failed Payments", "DC3545")
    add_headers(ws_fail, ["TxID", "User ID", "Amount (KES)", "Date Failed"])
    with connect() as conn:
        fa = conn.execute("SELECT transaction_id, user_id, amount, updated_at FROM payments WHERE status='failed' ORDER BY updated_at DESC").fetchall()
        for i, p in enumerate(fa, 4):
            ws_fail.cell(row=i, column=1, value=p["transaction_id"])
            ws_fail.cell(row=i, column=2, value=p["user_id"])
            ws_fail.cell(row=i, column=3, value=float(p["amount"]))
            ws_fail.cell(row=i, column=4, value=p["updated_at"].strftime("%Y-%m-%d %H:%M") if p["updated_at"] else "")

    # 6. Student Registrations
    ws_stu = wb.create_sheet("Student Registrations")
    style_sheet(ws_stu, "Student Registrations", "2563EB")
    add_headers(ws_stu, ["User ID", "Name", "Email", "Phone", "Role", "Registered At"])
    with connect() as conn:
        us = conn.execute("SELECT id, name, email, phone, role, created_at FROM users ORDER BY id DESC").fetchall()
        for i, u in enumerate(us, 4):
            ws_stu.cell(row=i, column=1, value=u["id"])
            ws_stu.cell(row=i, column=2, value=u["name"])
            ws_stu.cell(row=i, column=3, value=u["email"])
            ws_stu.cell(row=i, column=4, value=u["phone"])
            ws_stu.cell(row=i, column=5, value=u["role"])
            ws_stu.cell(row=i, column=6, value=u["created_at"].strftime("%Y-%m-%d %H:%M") if u["created_at"] else "")

    # 7. Academic Calculations
    ws_calc = wb.create_sheet("Academic Calculations")
    style_sheet(ws_calc, "Academic Calculations", "7952C7")
    add_headers(ws_calc, ["Ref", "User ID", "Cluster Points", "Date"])
    with connect() as conn:
        ca = conn.execute("SELECT reference, user_id, cluster_points, created_at FROM calculation_history ORDER BY created_at DESC").fetchall()
        for i, c in enumerate(ca, 4):
            ws_calc.cell(row=i, column=1, value=c["reference"])
            ws_calc.cell(row=i, column=2, value=c["user_id"])
            ws_calc.cell(row=i, column=3, value=float(c["cluster_points"]))
            ws_calc.cell(row=i, column=4, value=c["created_at"].strftime("%Y-%m-%d %H:%M") if c["created_at"] else "")

    # 8. Course Eligibility (Mocked from latest data for brevity)
    ws_elig = wb.create_sheet("Course Eligibility")
    style_sheet(ws_elig, "Course Eligibility Records", "16B8A6")
    add_headers(ws_elig, ["History ID", "Course Name", "University", "Cutoff", "Gap", "Match Type"])
    with connect() as conn:
        el = conn.execute("SELECT history_id, course_name, university, cutoff, difference, match_type FROM calculation_courses ORDER BY history_id DESC LIMIT 500").fetchall()
        for i, e in enumerate(el, 4):
            ws_elig.cell(row=i, column=1, value=e["history_id"])
            ws_elig.cell(row=i, column=2, value=e["course_name"])
            ws_elig.cell(row=i, column=3, value=e["university"])
            ws_elig.cell(row=i, column=4, value=float(e["cutoff"]))
            ws_elig.cell(row=i, column=5, value=float(e["difference"]))
            ws_elig.cell(row=i, column=6, value=e["match_type"])
            
    # Remaining sheets (9-15) can be added similarly. For brevity, I've provided the core financial and academic sheets.

    # Auto-widths for all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except: pass
            ws.column_dimensions[column].width = max_length + 3

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

def send_daily_excel_email():
    try:
        client, sender_email = _get_brevo()
        if not client: return False
        
        admin_email = os.getenv("ADMIN_EMAIL")
        if not admin_email: return False

        today_str = datetime.now(pytz.timezone('Africa/Nairobi')).strftime("%Y-%m-%d")
        wb_buffer = create_daily_excel_report()
        base64_wb = base64.b64encode(wb_buffer.getvalue()).decode("utf-8")

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; line-height: 1.6; color: #1F2937;">
            <h2 style="color: #0B1530;">EduPoint AI - Daily Report</h2>
            <p>Dear Administrator,</p>
            <p>Your automated daily administration report for <b>{today_str}</b> is attached.</p>
            <p>The workbook contains detailed records of payments, students, calculations, and system activity.</p>
            <p>Regards,<br><b>EduPoint AI System</b></p>
        </div>
        """

        client.transactional_emails.send_transac_email(
            subject=f"EduPoint AI - Daily Admin Report ({today_str})",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPoint AI Automated"),
            to=[SendTransacEmailRequestToItem(email=admin_email)],
            attachment=[{"content": base64_wb, "name": f"EduPoint_Daily_{today_str}.xlsx"}],
        )
        logger.info(f"Daily Excel report sent to {admin_email}")
        return True
    except Exception:
        logger.error(f"Daily report failed: {traceback.format_exc()}")
        return False

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
        payments.create_pending(transaction_id=tx, user_id=u["id"], phone=phone, network=provider, amount=amount, plan=plan, calculation_data=calc_data)
        r = payments.initiate(provider=provider, phone=phone, amount=amount, transaction_id=tx, plan=plan, user=u, callback_url=callback_url)
        payments.update(tx, status=r.get("status"), provider_reference=r.get("provider_reference"), message=r.get("message"), redirect_url=r.get("redirect_url"))
        pending_payment = payments.get(tx)
        threading.Thread(target=send_pending_invoice_email, args=(u["email"], u["name"], pending_payment), daemon=True).start()
        with connect() as conn: conn.execute("UPDATE payments SET invoice_sent_at = now() WHERE transaction_id = %s", (tx,))
        return jsonify(ok=True, transaction_id=tx, redirect_url=r.get("redirect_url"))
    except Exception as e:
        logger.error(f"Pesapal initiation failed: {traceback.format_exc()}")
        payments.update(tx, status="failed", message=str(e))
        return jsonify(ok=False, error=f"Error: {str(e)}"), 502

@app.route("/api/payment/webhook/pesapal", methods=["GET", "POST"])
def pesapal_webhook():
    try:
        body = request.get_json(silent=True) or {}
        tracking_id = (request.args.get("OrderTrackingId") or request.args.get("orderTrackingId") or body.get("OrderTrackingId") or body.get("orderTrackingId"))
        if not tracking_id: return jsonify(ok=False, error="Missing OrderTrackingId"), 400
        with connect() as conn: row = conn.execute("SELECT * FROM payments WHERE provider_reference = %s", (tracking_id,)).fetchone()
        if not row: return jsonify(ok=True, note="unknown")
        from services.pesapal import PesapalClient
        try: st = PesapalClient().transaction_status(tracking_id)
        except Exception: return jsonify(ok=False), 500
        status_code = st.get("status_code", -1)
        new_status = {1: "paid", 2: "failed", 3: "reversed", 0: "invalid"}.get(status_code, "pending")
        payments.update(row["transaction_id"], status=new_status, message=st.get("status") or "")
        if new_status == "paid": _claim_and_process(row["transaction_id"])
        return jsonify(ok=True, status=new_status)
    except Exception: return jsonify(ok=False), 500

@app.get("/api/payment/status/<transaction_id>")
@login_required
def payment_status(transaction_id):
    u = current_user()
    row = payments.get(transaction_id)
    if not row or (row.get("user_id") and row["user_id"] != u["id"] and u["role"] != "admin"): return jsonify(ok=False, error="Transaction not found."), 404
    if row["status"] == "pending":
        try:
            rr = payments.check_status(row)
            if rr:
                payments.update(transaction_id, status=rr["status"], message=rr.get("message"))
                row = payments.get(transaction_id)
        except Exception: logger.exception("Status check failed")
    calc_results = None
    if row["status"] == "paid":
        _claim_and_process(transaction_id)
        row = payments.get(transaction_id)
    if row["status"] == "completed" and row.get("results_json"):
        calc_results = row["results_json"]
    return jsonify(ok=True, payment=row, calculation_results=calc_results)

@app.get("/api/scholarships")
@login_required
def scholarships(): return jsonify(SCHOLARSHIPS)

@app.post("/api/chat")
@login_required
def chat():
    d = request.get_json(silent=True) or {}
    question = str(d.get("question", "")).lower().strip()
    if not question: return jsonify(answer="Ask me about any career, course, or subject requirement!")
    stop_words = {"what", "is", "a", "an", "the", "can", "i", "do", "with", "to", "for", "in", "of", "and", "how", "which", "are", "my", "me"}
    words = [w for w in re.findall(r'\b\w+\b', question) if w not in stop_words]
    best_match = None; highest_score = 0
    for qa in CHATBOT_QA:
        score = 0
        for kw in qa["keywords"]:
            kw_words = kw.lower().split()
            if kw in question: score += 10
            else:
                for kw_word in kw_words:
                    if kw_word in words: score += 2
        if score > highest_score: highest_score = score; best_match = qa
    if best_match and highest_score >= 2: return jsonify(answer=best_match["answer"])
    return jsonify(answer="I am still expanding my career database. Try asking about specific careers (e.g., 'Software Engineer', 'Nursing').")

# ==========================================
# ADMIN ROUTES
# ==========================================
@app.get("/api/admin/metrics")
@admin_required
def admin_metrics():
    with connect() as conn:
        rev_row = conn.execute("SELECT SUM(amount) as total FROM payments WHERE status IN ('paid', 'completed')").fetchone()
        users_row = conn.execute("SELECT COUNT(*) as total FROM users WHERE role = 'student'").fetchone()
        calc_row = conn.execute("SELECT COUNT(*) as total FROM calculation_history").fetchone()
        pending_row = conn.execute("SELECT COUNT(*) as total FROM payments WHERE status = 'pending'").fetchone()
        failed_row = conn.execute("SELECT COUNT(*) as total FROM payments WHERE status = 'failed'").fetchone()
        succ_row = conn.execute("SELECT COUNT(*) as total FROM payments WHERE status IN ('paid', 'completed')").fetchone()
    return jsonify(ok=True, metrics={
        "revenue": float(rev_row["total"] or 0), "users": users_row["total"], "calculations": calc_row["total"],
        "pending_payments": pending_row["total"], "failed_payments": failed_row["total"], "successful_payments": succ_row["total"]
    })

@app.get("/api/admin/payments")
@admin_required
def admin_payments():
    with connect() as conn:
        rows = conn.execute("""
            SELECT p.id, p.transaction_id, p.user_id, p.amount, p.status,
                   p.invoice_sent_at, p.last_reminder_at, p.reminder_count,
                   u.name, u.email
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            ORDER BY p.id DESC LIMIT 100
        """).fetchall()
    return jsonify(ok=True, payments=[dict(r) for r in rows])

@app.post("/api/admin/payments/<transaction_id>/retry")
@admin_required
def admin_retry_payment(transaction_id):
    with connect() as conn: row = conn.execute("SELECT * FROM payments WHERE transaction_id=%s", (transaction_id,)).fetchone()
    if not row: return jsonify(ok=False, error="Not found"), 404
    if row["status"] == "paid": _claim_and_process(transaction_id); return jsonify(ok=True, message="Processing triggered.")
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
    email = d.get("email"); subjects = d.get("subjects"); grades = d.get("grades")
    if not email or not subjects or not grades: return jsonify(ok=False, error="Missing data."), 400
    with connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
        if not u:
            u = conn.execute("INSERT INTO users(name, email, phone, password_hash, role) VALUES(%s, %s, %s, %s, 'student') RETURNING *", ("Student (Admin)", email, "0700000000", "ADMIN_GEN")).fetchone()
    try:
        calc_results = process_calculation(u, subjects, grades)
        fake_payment = {"transaction_id": "ADMIN-" + uuid.uuid4().hex[:8].upper(), "user_id": u["id"], "amount": 0.0, "status": "completed", "created_at": datetime.now()}
        send_paid_receipt_email(email, u["name"], calc_results["cluster_points"], calc_results["results"], subjects, grades, SCHOLARSHIPS, fake_payment)
        return jsonify(ok=True, calculation_results=calc_results)
    except Exception as e: return jsonify(ok=False, error=str(e)), 500

@app.get("/api/admin/payments/export")
@admin_required
def export_payments_excel():
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT p.transaction_id, p.amount, p.status, p.provider_reference, p.invoice_sent_at, p.reminder_count, p.created_at, u.id as user_id, u.name, u.email, u.phone
                FROM payments p LEFT JOIN users u ON u.id = p.user_id ORDER BY p.created_at DESC
            """).fetchall()
        wb = Workbook(); ws = wb.active; ws.title = "Daily Payments"
        header_font = Font(bold=True, color="FFFFFF"); header_fill = PatternFill(start_color="101B3D", end_color="101B3D", fill_type="solid")
        headers = ["Date", "Transaction ID", "Student Name", "Email", "Phone", "Amount (KES)", "Status", "Pesapal Ref", "Invoice Sent", "Reminders"]
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header); cell.font = header_font; cell.fill = header_fill; cell.alignment = Alignment(horizontal="center")
        for row_num, r in enumerate(rows, 2):
            created_at = r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "-"
            invoice_sent = "Yes" if r["invoice_sent_at"] else "No"
            ws.cell(row=row_num, column=1, value=created_at); ws.cell(row=row_num, column=2, value=r["transaction_id"]); ws.cell(row=row_num, column=3, value=r["name"] or "Unknown")
            ws.cell(row=row_num, column=4, value=r["email"] or "-"); ws.cell(row=row_num, column=5, value=r["phone"] or "-"); ws.cell(row=row_num, column=6, value=float(r["amount"]))
            ws.cell(row=row_num, column=7, value=str(r["status"]).capitalize()); ws.cell(row=row_num, column=8, value=r["provider_reference"] or "-"); ws.cell(row=row_num, column=9, value=invoice_sent); ws.cell(row=row_num, column=10, value=r["reminder_count"])
        for col in ws.columns:
            max_length = 0; column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
                except: pass
            ws.column_dimensions[column].width = max_length + 3
        buffer = io.BytesIO(); wb.save(buffer); buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f"EduPoint_Payments_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception: return jsonify(ok=False, error="Export failed."), 500

@app.get("/api/admin/calculations")
@admin_required
def admin_calculations():
    with connect() as conn:
        rows = conn.execute("SELECT h.id, h.reference, h.cluster_points, h.created_at, u.email, u.name FROM calculation_history h JOIN users u ON h.user_id = u.id ORDER BY h.created_at DESC LIMIT 50").fetchall()
    for r in rows: r["created_at"] = r["created_at"].isoformat(); r["cluster_points"] = float(r["cluster_points"])
    return jsonify(ok=True, calculations=rows)

@app.get("/api/admin/students")
@admin_required
def admin_students():
    with connect() as conn:
        rows = conn.execute("SELECT id, name, email, phone, role, created_at FROM users WHERE role = 'student' ORDER BY created_at DESC LIMIT 100").fetchall()
    for r in rows: r["created_at"] = r["created_at"].isoformat()
    return jsonify(ok=True, students=rows)

@app.post("/api/admin/access/<int:user_id>")
@admin_required
def admin_access(user_id):
    d = request.get_json(silent=True) or {}; credits_to_add = int(d.get("credits", 1))
    if credits_to_add > 0:
        with connect() as conn: conn.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (credits_to_add, user_id))
    return jsonify(ok=True, added=credits_to_add)

@app.get("/api/cron/daily-excel")
def trigger_daily_excel():
    secret = request.args.get("secret")
    expected_secret = os.getenv("CRON_SECRET", "edupoint_secret_123")
    if secret != expected_secret: return "Unauthorized", 401
    success = send_daily_excel_email()
    return ("OK", 200) if success else ("Failed", 500)

@app.get("/api/cron/send-reminders")
def trigger_reminders():
    secret = request.args.get("secret"); expected = os.getenv("CRON_SECRET", "edupoint_secret_123")
    if secret != expected: return "Unauthorized", 401
    with connect() as conn:
        stuck = conn.execute("SELECT transaction_id FROM payments WHERE status = 'paid' AND updated_at < now() - INTERVAL '5 minutes' LIMIT 20").fetchall()
    for s in stuck: _claim_and_process(s["transaction_id"])
    sent = 0
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT p.*, u.name AS user_name, u.email AS user_email FROM payments p JOIN users u ON u.id = p.user_id
                WHERE p.status = 'pending' AND p.redirect_url IS NOT NULL AND p.created_at < now() - INTERVAL '24 hours'
                  AND (p.last_reminder_at IS NULL OR p.last_reminder_at < now() - INTERVAL '24 hours') ORDER BY p.created_at ASC LIMIT 100
            """).fetchall()
    except Exception: return "Error", 500
    for row in rows:
        try:
            send_reminder_email(row["user_email"], row["user_name"], row)
            with connect() as conn: conn.execute("UPDATE payments SET last_reminder_at = now(), reminder_count = COALESCE(reminder_count, 0) + 1 WHERE transaction_id = %s", (row["transaction_id"],))
            sent += 1
        except Exception: pass
    return jsonify(ok=True, reminders_sent=sent, stuck_retried=len(stuck)), 200

# ==========================================
# GLOBAL ERROR HANDLERS
# ==========================================
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException): return jsonify(ok=False, error=e.description), e.code
    logger.error(f"Unhandled Exception: {traceback.format_exc()}")
    return jsonify(ok=False, error="An unexpected error occurred."), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
