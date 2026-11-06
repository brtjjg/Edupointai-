#!/usr/bin/env python3
import os
import uuid
import logging
import base64
import threading
import random
import string
import io
from datetime import datetime

import psycopg
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Google Auth
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Brevo Email SDK
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem

# ReportLab PDF Libraries
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
from reportlab.lib.colors import HexColor
import qrcode

# Local imports
from data import W, BEST, MAX, P, SCHOLARSHIPS, CHATBOT_QA, PAYMENT_PLANS
from db import connect, init_db
from auth import (
    current_user, public_user, login_required, admin_required,
    hash_password, verify_password, create_session, destroy_session, bearer_token,
)
from services.payments import PaymentService, normalize_phone, validate_provider

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["JSON_SORT_KEYS"] = False

FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGINS}}, allow_headers=["Content-Type", "Authorization"], methods=["GET", "POST", "OPTIONS"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
payments = PaymentService()

# ---------------- Helper Functions ----------------

def has_paid_access(user_id):
    with connect() as conn:
        r = conn.execute("SELECT paid FROM access WHERE user_id=%s", (user_id,)).fetchone()
    return bool(r and r["paid"])

def set_access(user_id, paid, plan=None, tx=None):
    with connect() as conn:
        conn.execute(
            """INSERT INTO access(user_id,paid,plan,transaction_id,updated_at)
               VALUES(%s,%s,%s,%s,now())
               ON CONFLICT(user_id) DO UPDATE SET paid=EXCLUDED.paid, plan=EXCLUDED.plan, transaction_id=EXCLUDED.transaction_id, updated_at=now()""",
            (user_id, 1 if paid else 0, plan, tx),
        )

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
            conn.execute("UPDATE users SET role='admin', password_hash=%s WHERE id=%s", (hash_password(password), row["id"]))
        else:
            conn.execute(
                """INSERT INTO users(name,email,phone,password_hash,referral_code,role) VALUES(%s,%s,%s,%s,%s,'admin')""",
                ("EduPoint Administrator", email, "", hash_password(password), "ADMIN"),
            )
ensure_admin()

def generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships):
    buffer = io.BytesIO()
    
    # Colors
    NAVY = HexColor("#172554")
    PURPLE = HexColor("#7546C8")
    BLUE = HexColor("#38BDF8")
    PALE = HexColor("#F4F6FC")
    LIGHT_BLUE = HexColor("#EAF3FF")
    LIGHT_PURPLE = HexColor("#F1ECFB")
    INK = HexColor("#1F2937")
    MUTED = HexColor("#64748B")
    BORDER = HexColor("#DCE3EF")
    GREEN = HexColor("#15803D")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.white, spaceAfter=2))
    styles.add(ParagraphStyle(name="Tagline", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=HexColor("#DCE8FF")))
    styles.add(ParagraphStyle(name="HeroTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_LEFT, textColor=NAVY, spaceAfter=5))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=9, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=NAVY))
    styles.add(ParagraphStyle(name="WhiteSmall", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, textColor=colors.white))

    def P(text, style="BodySmall"): return Paragraph(str(text), styles[style])

    def header_footer(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY)
        # FIXED: Proper Python math with * mm
        canvas.rect(0, h - 8*mm, w, 8*mm, stroke=0, fill=1)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.6)
        canvas.line(18*mm, 16*mm, w - 18*mm, 16*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 10.5*mm, "EduPointAI  |  Your Education. Your Future.")
        canvas.drawRightString(w - 18*mm, 10.5*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=17*mm, bottomMargin=23*mm)
    story = []

    # 1. Brand Banner
    brand = Table([[P("EduPointAI", "Brand"), P("STUDENT RESULTS REPORT<br/>COURSE & SCHOLARSHIP MATCHING", "WhiteSmall")]], colWidths=[75*mm, 99*mm], rowHeights=[22*mm])
    brand.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), NAVY), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 12), ("RIGHTPADDING", (0,0), (-1,-1), 12), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7), ("ALIGN", (1,0), (1,0), "RIGHT")]))
    story += [brand, Spacer(1, 8*mm)]

    # 2. Hero Title
    story += [P("Your academic assessment is ready", "HeroTitle"), P("A personalized overview of your academic performance, course qualifications and scholarship opportunities.", "Sub"), Spacer(1, 5*mm)]

    # 3. Student Identity Strip
    today = datetime.now().strftime("%d %b %Y, %H:%M")
    ref = "EP-2026-" + ''.join(random.choices(string.digits, k=6))
    student = Table([[P("STUDENT", "Tiny"), P("REPORT STATUS", "Tiny"), P("REPORT REFERENCE", "Tiny")],
                     [P(user_name, "BodySmall"), P("Assessment complete", "BodySmall"), P(ref, "BodySmall")]],
                    colWidths=[58*mm, 58*mm, 58*mm])
    student.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PALE), ("BOX", (0,0), (-1,-1), 0.7, BORDER), ("INNERGRID", (0,0), (-1,-1), 0.5, BORDER), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 9), ("RIGHTPADDING", (0,0), (-1,-1), 9), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
    story += [student, Spacer(1, 5*mm)]

    # 4. KPI Cards
    qualified = [r for r in results if r['match'] == 'qualified']
    cards = Table([[P("CLUSTER POINTS", "CardLabel"), P("QUALIFIED COURSES", "CardLabel"), P("SCHOLARSHIP MATCHES", "CardLabel")],
                   [P(str(cluster_points), "CardValue"), P(str(len(qualified)), "CardValue"), P("See below", "BodySmall")]],
                  colWidths=[58*mm, 58*mm, 58*mm])
    cards.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), LIGHT_BLUE), ("BACKGROUND", (1,0), (1,-1), LIGHT_PURPLE), ("BACKGROUND", (2,0), (2,-1), PALE), ("BOX", (0,0), (-1,-1), 0.6, BORDER), ("INNERGRID", (0,0), (-1,-1), 1, colors.white), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10), ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
    story += [cards, Spacer(1, 5*mm)]

    # 5. Academic Profile Table
    story += [P("01  Academic profile", "Section")]
    grades_data = [[P("SUBJECT", "Tiny"), P("GRADE", "Tiny"), P("POINTS", "Tiny")]]
    for i in range(7):
        subj_name = subjects.get(str(i), f"Subject {i+1}")
        grade = grades.get(str(i), "-")
        pts = W.get(grade.upper(), 0) if grade else 0
        grades_data.append([P(subj_name, "BodySmall"), P(grade, "BodySmall"), P(str(pts), "BodySmall")])
    
    gt = Table(grades_data, colWidths=[100*mm, 37*mm, 37*mm], repeatRows=1)
    gt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), PALE), ("TEXTCOLOR", (0,0), (-1,0), NAVY), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
    story += [gt, Spacer(1, 5*mm)]

    # 6. Qualified Courses Table
    story += [P("02  Qualified courses", "Section"), P("The following courses have been identified based on the assessment criteria applied by EduPointAI. Confirm current entry requirements with the relevant institution.", "Sub"), Spacer(1, 2*mm)]
    course_data = [[P("#", "Tiny"), P("COURSE / PROGRAMME", "Tiny"), P("INSTITUTION", "Tiny"), P("CUTOFF", "Tiny")]]
    for idx, c in enumerate(qualified[:15]): # Limit to 15 for fitting
        course_data.append([P(str(idx+1), "BodySmall"), P(c['n'], "BodySmall"), P(c['u'], "BodySmall"), P(str(c['c']), "BodySmall")])
    
    if len(qualified) == 0:
        course_data.append([P("-", "BodySmall"), P("No courses qualified for yet based on your current grades.", "BodySmall"), P("", "BodySmall"), P("", "BodySmall")])

    ct = Table(course_data, colWidths=[10*mm, 70*mm, 60*mm, 34*mm], repeatRows=1)
    ct.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), LIGHT_BLUE), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story += [ct, Spacer(1, 5*mm)]

    # 7. Scholarships
    story += [P("03  Scholarship opportunities", "Section")]
    sch_data = [[P("SCHOLARSHIP", "Tiny"), P("AMOUNT", "Tiny"), P("DEADLINE", "Tiny")]]
    for s in scholarships[:10]: # Limit to 10 for fitting
        sch_data.append([P(s['name'], "BodySmall"), P(s['amount'], "BodySmall"), P(s['deadline'], "BodySmall")])
        
    st = Table(sch_data, colWidths=[90*mm, 50*mm, 34*mm], repeatRows=1)
    st.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), LIGHT_PURPLE), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story += [st, Spacer(1, 6*mm)]

    # 8. Footer Details & QR Code
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(f"EduPointAI|Ref:{ref}|Name:{user_name}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    qr_image = RLImage(qr_buffer, width=18*mm, height=18*mm)
    
    footer_table = Table([[qr_image, P(f"Report Reference: {ref}<br/>Generated: {today}<br/>Valid for: 12 Months", "BodySmall"), P("EduPointAI<br/>Your Education. Your Future.", "Brand")]], colWidths=[20*mm, 60*mm, 94*mm])
    footer_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 5), ("TEXTCOLOR", (2,0), (2,0), NAVY)]))
    story += [footer_table]

    # Build PDF
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    buffer.seek(0)
    return buffer

def send_pdf_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships):
    try:
        # 1. Generate PDF using ReportLab
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')

        # 2. Setup Brevo Client
        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")
        
        if not api_key or not sender_email:
            logger.warning("Brevo API key or Sender Email missing. Skipping email.")
            return

        client = Brevo(api_key=api_key)

        # 3. HTML Email Body
        qualified_count = len([r for r in results if r['match'] == 'qualified'])
        email_html = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
            <h2 style="color: #1a1c33;">Dear {user_name},</h2>
            <p>Thank you for using <b>EduPointAI</b>.</p>
            <p>Your academic assessment has been successfully processed. Your personalized calculation report is ready.</p>
            
            <div style="background: #f4f6f8; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1a1c33;">Your assessment summary:</h3>
                <ul style="list-style-type: none; padding-left: 0;">
                    <li><b>Cluster Points:</b> {cluster_points}</li>
                    <li><b>Qualified Courses:</b> {qualified_count}</li>
                    <li><b>Scholarship Opportunities:</b> Included in your report</li>
                </ul>
            </div>

            <h3 style="color: #1a1c33;">What you will find in your report:</h3>
            <ol>
                <li>Your calculated academic performance.</li>
                <li>University courses you qualify for.</li>
                <li>Available scholarship opportunities matching your academic profile.</li>
                <li>Relevant eligibility information and guidance.</li>
            </ol>

            <h3 style="color: #1a1c33;">Access your results</h3>
            <p>You can preview your complete report directly from your EduPointAI account. A PDF copy is also attached to this email for downloading and future reference.</p>
            
            <p style="font-size: 12px; color: #666; font-style: italic;">
                Please note that course qualification and scholarship eligibility do not guarantee admission or scholarship awards. Final decisions are made by the respective institutions and scholarship providers.
            </p>

            <p>Thank you for trusting EduPointAI with your academic journey.</p>
            <br>
            <p>Kind regards,</p>
            <p><b>EduPointAI Team</b><br><span style="color: #666; font-size: 12px;">Your Education. Your Future.</span></p>
        </div>
        """

        # 4. Send Email via Brevo
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Calculation Report - Course & Scholarship Qualifications",
            html_content=email_html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": pdf_base64, "name": "EduPointAI_Results_Report.pdf"}]
        )
        logger.info(f"Email successfully sent to {user_email} via Brevo.")
        
    except Exception as e:
        logger.error(f"Failed to send email via Brevo: {e}")

# ---------------- Routes ----------------

@app.get("/health")
def health(): 
    return jsonify(ok=True, service="edupoint-api")

@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    name = str(d.get("name", "")).strip()
    email = str(d.get("email", "")).strip().lower()
    phone = normalize_phone(d.get("phone", ""))
    password = str(d.get("password", ""))
    ref = str(d.get("referral_code") or "").strip().upper() or None

    if len(name) < 2: return jsonify(ok=False, error="Enter your full name."), 400
    if "@" not in email: return jsonify(ok=False, error="Enter a valid email address."), 400
    if not phone: return jsonify(ok=False, error="Enter a valid Kenyan mobile number."), 400
    if len(password) < 6: return jsonify(ok=False, error="Password must contain at least 6 characters."), 400

    try:
        with connect() as conn:
            row = conn.execute(
                """INSERT INTO users(name,email,phone,password_hash,referral_code,role) 
                   VALUES(%s,%s,%s,%s,%s,'student') RETURNING id""", 
                (name, email, phone, hash_password(password), ref)
            ).fetchone()
            uid = row["id"]
    except psycopg.errors.UniqueViolation:
        return jsonify(ok=False, error="An account with that email already exists."), 409

    token = create_session(uid)
    return jsonify(ok=True, token=token, redirect="/dashboard.html")

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    email = str(d.get("email", "")).strip().lower()
    password = str(d.get("password", ""))
    
    with connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email=%s AND active=1", (email,)).fetchone()
        
    if not u or not verify_password(password, u["password_hash"]):
        return jsonify(ok=False, error="Incorrect email or password."), 401
        
    token = create_session(u["id"])
    return jsonify(
        ok=True, token=token, user=public_user(u), 
        redirect="/admin.html" if u["role"] == "admin" else "/dashboard.html"
    )

@app.post("/api/auth/google")
def google_login():
    d = request.get_json(silent=True) or {}
    token = d.get("credential")
    if not token:
        return jsonify(ok=False, error="No Google credential provided."), 400
        
    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), os.getenv("GOOGLE_CLIENT_ID"))
        email = idinfo["email"].strip().lower()
        name = idinfo.get("name", "Google User")
        
        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            if not u:
                u = conn.execute(
                    """INSERT INTO users(name, email, phone, password_hash, role) 
                       VALUES(%s, %s, %s, %s, 'student') RETURNING *""", 
                    (name, email, "0700000000", "GOOGLE_AUTH")
                ).fetchone()
                
        session_token = create_session(u["id"])
        return jsonify(ok=True, token=session_token, user=public_user(u), redirect="/dashboard.html")
    except ValueError:
        return jsonify(ok=False, error="Invalid Google token."), 401

@app.post("/api/logout")
@login_required
def logout():
    destroy_session(bearer_token())
    return jsonify(ok=True)

@app.get("/api/me")
@login_required
def me():
    u = current_user()
    return jsonify(
        ok=True, 
        user=public_user(u), 
        paid=has_paid_access(u["id"]), 
        credits=u.get("credits", 0)
    )

@app.get("/api/plans")
def plans(): 
    return jsonify(PAYMENT_PLANS)

@app.get("/api/providers")
def providers(): 
    return jsonify(payments.available_providers())

@app.post("/api/payment/initiate")
@login_required
def initiate_payment():
    u = current_user()
    d = request.get_json(silent=True) or {}
    provider = (d.get("provider") or "").strip().lower()
    phone = normalize_phone(d.get("phone") or u["phone"])
    plan = (d.get("plan") or "standard").strip().lower()

    if plan not in PAYMENT_PLANS: return jsonify(ok=False, error="Invalid payment plan."), 400
    if not validate_provider(provider): return jsonify(ok=False, error="Unsupported payment network."), 400
    if not phone: return jsonify(ok=False, error="Enter a valid Kenyan mobile number."), 400

    amount = PAYMENT_PLANS[plan]["amount"]
    tx = "EDU-" + uuid.uuid4().hex[:16].upper()
    callback_url = f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/payment-callback.html"
    
    payments.create_pending(transaction_id=tx, phone=phone, network=provider, amount=amount, plan=plan, user_id=u["id"])
    
    try:
        r = payments.initiate(provider=provider, phone=phone, amount=amount, transaction_id=tx, plan=plan, user=u, callback_url=callback_url)
        payments.update(tx, status=r.get("status", "pending"), provider_reference=r.get("provider_reference"), message=r.get("message"), redirect_url=r.get("redirect_url"))
        return jsonify(
            ok=True, transaction_id=tx, status=r.get("status", "pending"), 
            message=r.get("message", "Payment request created."), 
            instructions=r.get("instructions", []), 
            redirect_url=r.get("redirect_url")
        )
    except Exception:
        logger.exception("Payment initiation failed")
        payments.update(tx, status="failed", message="Payment could not be started.")
        return jsonify(ok=False, transaction_id=tx, error="Payment could not be started."), 502

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

    if row["status"] == "paid" and row.get("user_id"):
        add_credit(row["user_id"])
        payments.update(transaction_id, status="completed")
        row["status"] = "completed"

    with connect() as conn:
        fresh_u = conn.execute("SELECT credits FROM users WHERE id=%s", (u["id"],)).fetchone()

    return jsonify(ok=True, payment=row, credits=fresh_u.get("credits", 0))

@app.route("/api/payment/webhook/<provider>", methods=["GET", "POST"])
def payment_webhook(provider):
    if not validate_provider(provider): 
        return jsonify(ok=False, error="Unsupported provider"), 404
        
    payload = (request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict())

    if provider == "pesapal":
        r = payments.handle_pesapal_ipn(payload)
        if r.get("ok"):
            row = payments.get(r["transaction_id"])
            if row and row.get("user_id") and row["status"] == "paid":
                add_credit(row["user_id"])
                payments.update(row["transaction_id"], status="completed")
                
        return jsonify({
            "orderNotificationType": payload.get("orderNotificationType", "IPNCHANGE"), 
            "orderTrackingId": payload.get("orderTrackingId", ""), 
            "orderMerchantReference": payload.get("orderMerchantReference", ""), 
            "status": 200 if r.get("ok") else 500
        }), 200

    r = payments.handle_webhook(provider, payload)
    if not r.get("ok"): 
        return jsonify(r), 400
        
    row = payments.get(r.get("transaction_id"))
    if row and r.get("status") == "paid" and row.get("user_id"):
        add_credit(row["user_id"])
        
    return jsonify(ok=True)

@app.post("/api/calculate")
@login_required
def calculate():
    u = current_user()
    if u.get("credits", 0) <= 0:
        return jsonify(ok=False, error="You have 0 calculations left. Please pay 100 KES to buy 1 more calculation.", code="payment_required"), 402
        
    d = request.get_json(silent=True) or {}
    grades = d.get("grades", {})
    subjects = d.get("subjects", {})
    
    try:
        vals = [W[str(v).strip().upper()] for v in grades.values() if str(v).strip().upper() in W]
        vals = sorted(vals, reverse=True)[:7]
        if len(vals) < 7: return jsonify(ok=False, error="Enter at least 7 valid grades."), 400
        
        cp = (sum(vals) / BEST) * MAX
        out = []
        for course in P:
            diff = cp - course["c"]
            out.append({**course, "difference": round(diff, 3), "match": "qualified" if diff >= 0 else ("close" if diff >= -2 else "not_qualified")})
            
        with connect() as conn:
            conn.execute("UPDATE users SET credits = credits - 1 WHERE id=%s", (u["id"],))
            
        threading.Thread(
            target=send_pdf_email, 
            args=(u["email"], u["name"], round(cp, 3), out, subjects, grades, SCHOLARSHIPS)
        ).start()
            
        return jsonify(ok=True, cluster_points=round(cp, 3), results=out, credits_left=u["credits"] - 1)
    except Exception as e:
        return jsonify(ok=False, error=f"Invalid grades: {e}"), 400

@app.get("/api/scholarships")
@login_required
def scholarships():
    return jsonify(SCHOLARSHIPS)

@app.post("/api/chat")
@login_required
def chat():
    q = str((request.get_json(silent=True) or {}).get("question", "")).lower().strip()
    if not q: 
        return jsonify(answer="Ask me a KUCCPS, course, cluster-points or scholarship question.")
    for x in CHATBOT_QA:
        if any(k in q for k in x["keywords"]): 
            return jsonify(answer=x["answer"])
    return jsonify(answer="I can help with cluster points, KUCCPS courses, admission chances, transfers, scholarships and university requirements.")

@app.get("/api/admin/users")
@admin_required
def admin_users():
    with connect() as conn:
        rows = conn.execute("SELECT id,name,email,phone,role,active,referral_code,credits,created_at FROM users ORDER BY id DESC").fetchall()
    for r in rows:
        r["active"] = bool(r["active"])
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
    return jsonify(ok=True, users=rows)

@app.get("/api/admin/payments")
@admin_required
def admin_payments():
    with connect() as conn:
        rows = conn.execute("SELECT id,transaction_id,user_id,phone,network,amount,plan,status,provider_reference,created_at FROM payments ORDER BY id DESC LIMIT 200").fetchall()
    for r in rows:
        r["amount"] = float(r["amount"])
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
    return jsonify(ok=True, payments=rows)

@app.post("/api/admin/user/<int:user_id>/toggle")
@admin_required
def admin_toggle_user(user_id):
    with connect() as conn:
        r = conn.execute("SELECT active FROM users WHERE id=%s", (user_id,)).fetchone()
        if not r: 
            return jsonify(ok=False, error="User not found."), 404
        conn.execute("UPDATE users SET active=%s WHERE id=%s", (0 if r["active"] else 1, user_id))
    return jsonify(ok=True)

@app.post("/api/admin/access/<int:user_id>")
@admin_required
def admin_access(user_id):
    d = request.get_json(silent=True) or {}
    credits_to_add = int(d.get("credits", 1))
    
    if credits_to_add > 0:
        with connect() as conn:
            conn.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (credits_to_add, user_id))
            
    return jsonify(ok=True, added=credits_to_add)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
