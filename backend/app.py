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
# HELPER FUNCTIONS
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
# PDF GENERATION (ALL COURSES + SUBJECT REQUIREMENTS)
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

    # ============ COVER ============
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

    # Subject breakdown
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

    # Top 10
    story.append(PageBreak())
    story += [P("02  Top 10 Recommended Courses", "Section"),
              P(f"These are the highest-cutoff courses you currently qualify for. Your cluster ({cluster_points}) meets or exceeds their cutoffs — great choices to prioritise in KUCCPS.", "Sub"),
              Spacer(1, 3*mm)]
    if qualified:
        story.append(build_course_table(qualified[:10], GREEN_HDR))
    else:
        story.append(P("You do not yet meet the cutoff for any course in our database. See the Close (±2) and Not Yet Qualified sections below — they show the shortest paths forward.", "BodySmall"))

    # All qualified
    if qualified:
        story.append(PageBreak())
        story += [P(f"03  All Courses You Qualify For ({len(qualified)})", "Section"),
                  P("Your cluster meets or exceeds every cutoff listed below. These are safe / competitive choices.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(qualified, GREEN_HDR)]

    # Close matches
    if close:
        story.append(PageBreak())
        story += [P(f"04  Close Matches — Within 2.0 Points ({len(close)})", "Section"),
                  P("You are just below the cutoff. These may become reachable through a grade revision, diploma route, or inter-institution transfer later.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(close, AMBER_HDR)]

    # Not yet qualified
    if not_qual:
        story.append(PageBreak())
        story += [P(f"05  Not Yet Qualified ({len(not_qual)})", "Section"),
                  P("Cutoff is more than 2.0 points above your cluster. Use these as a roadmap for upgrading grades, retaking, or entering via a diploma pathway.", "Sub"),
                  Spacer(1, 3*mm),
                  build_course_table(not_qual, RED_HDR)]

    # Scholarships
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


def send_pending_invoice_email(user_email, user_name, payment):
    try:
        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode('utf-8')
        api_key = os.getenv("BREVO_API_KEY"); sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return
        client = Brevo(api_key=api_key)
        html = f"<div style='font-family: Arial;'><h2>Dear {user_name},</h2><p>Your payment has been initiated. Please find your pending invoice attached.</p><p>Complete the payment on the Pesapal page to unlock your results. Once paid, you will receive a final Receipt and your Results Report.</p><p>EduPointAI Team</p></div>"
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Pending Invoice",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Pending_Invoice_{payment['transaction_id']}.pdf"}]
        )
        logger.info(f"Sent pending invoice to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send pending invoice: {traceback.format_exc()}")


def send_paid_receipt_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships, payment):
    try:
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        attachments = [{"content": pdf_base64, "name": "EduPointAI_Results.pdf"}]

        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode('utf-8')
        attachments.append({"content": inv_base64, "name": f"Receipt_{payment['transaction_id']}.pdf"})

        api_key = os.getenv("BREVO_API_KEY"); sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return
        client = Brevo(api_key=api_key)
        html = (
            f"<div style='font-family: Arial; line-height: 1.6;'>"
            f"<h2>Dear {user_name},</h2>"
            f"<p>Your payment is confirmed and your comprehensive academic report is ready.</p>"
            f"<p><b>Cluster Points:</b> {cluster_points}</p>"
            f"<p>Your attached <b>Comprehensive Results Report</b> includes:</p>"
            f"<ul>"
            f"<li><b>Every course</b> in our database (200+)</li>"
            f"<li>Courses grouped by: <b>Qualified</b> • <b>Close (±2 points)</b> • <b>Not Yet Qualified</b></li>"
            f"<li>The <b>specific subjects each course requires</b> (e.g. Biology + Chemistry for Medicine)</li>"
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
            attachment=attachments
        )
        logger.info(f"Successfully sent results and receipt to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send email: {traceback.format_exc()}")


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
                u = conn.execute("INSERT INTO users(name, email, phone, password_hash, role, credits) VALUES(%s, %s, %s, %s, 'student', 0) RETURNING *", (name, email, "0700000000", "GOOGLE_AUTH")).fetchone()
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

    amount = PAYMENT_PLANS[plan]["amount"]
    tx = "EDU-" + uuid.uuid4().hex[:16].upper()
    callback_url = f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/"

    try:
        payments.create_pending(
            transaction_id=tx, user_id=u["id"], phone=phone,
            network=provider, amount=amount, plan=plan,
            calculation_data=calc_data
        )

        pending_payment = payments.get(tx)
        threading.Thread(target=send_pending_invoice_email, args=(u["email"], u["name"], pending_payment)).start()

        r = payments.initiate(provider=provider, phone=phone, amount=amount, transaction_id=tx, plan=plan, user=u, callback_url=callback_url)

        payments.update(tx, status=r.get("status"), provider_reference=r.get("provider_reference"), message=r.get("message"), redirect_url=r.get("redirect_url"))

        return jsonify(ok=True, transaction_id=tx, redirect_url=r.get("redirect_url"))

    except Exception as e:
        logger.error(f"Pesapal Error: {traceback.format_exc()}")
        payments.update(tx, status="failed", message=str(e))
        return jsonify(ok=False, error=f"Error: {str(e)}"), 502

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
    if row["status"] == "paid" and row.get("calculation_data"):
        add_credit(row["user_id"])
        payments.update(transaction_id, status="completed")
        row["status"] = "completed"
        try:
            calc_results = process_calculation(u, row["calculation_data"]["subjects"], row["calculation_data"]["grades"])

            threading.Thread(
                target=send_paid_receipt_email,
                args=(u["email"], u["name"], calc_results["cluster_points"], calc_results["results"],
                      row["calculation_data"]["subjects"], row["calculation_data"]["grades"], SCHOLARSHIPS, row)
            ).start()

            payments.update(transaction_id, calculation_data=None)
        except Exception as e:
            logger.error(f"Calculation failed post-payment: {e}")

    return jsonify(ok=True, payment=row, calculation_results=calc_results)

@app.get("/api/history")
@login_required
def get_history():
    u = current_user()
    with connect() as conn:
        rows = conn.execute("""SELECT h.*, (SELECT COUNT(*) FROM calculation_courses WHERE history_id = h.id AND match_type = 'qualified') as qual_count
               FROM calculation_history h WHERE h.user_id = %s ORDER BY h.created_at DESC""", (u["id"],)).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat(); r["cluster_points"] = float(r["cluster_points"])
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
        rows = conn.execute("SELECT id,transaction_id,user_id,amount,status FROM payments ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify(ok=True, payments=[dict(r) for r in rows])

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

        if success:
            return "OK", 200
        else:
            return "Failed to generate", 500

    except Exception as e:
        import traceback
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
