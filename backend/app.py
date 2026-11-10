#!/usr/bin/env python3
import os, uuid, logging, base64, threading, random, string, io, json, traceback
from datetime import datetime

import psycopg
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

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

from data import W, BEST, MAX, P, SCHOLARSHIPS, PAYMENT_PLANS
from db import connect, init_db
from auth import (
    current_user, public_user, login_required, admin_required,
    hash_password, verify_password, create_session, destroy_session, bearer_token,
)
from services.payments import PaymentService, normalize_phone, validate_provider
from services.reports import generate_and_send_reports 
from services.invoices import generate_invoice_pdf # NEW: Import the invoice generator

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
# CALCULATION LOGIC (No emailing here anymore)
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
# PDF GENERATION (Results + Invoice)
# ==========================================

def generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships):
    buffer = io.BytesIO()
    NAVY = HexColor("#172554"); PALE = HexColor("#F4F6FC"); LIGHT_BLUE = HexColor("#EAF3FF"); LIGHT_PURPLE = HexColor("#F1ECFB"); INK = HexColor("#1F2937"); MUTED = HexColor("#64748B"); BORDER = HexColor("#DCE3EF")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.white))
    styles.add(ParagraphStyle(name="HeroTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_LEFT, textColor=NAVY))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=9, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="CardValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=NAVY))
    styles.add(ParagraphStyle(name="WhiteSmall", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, textColor=colors.white))

    def P(text, style="BodySmall"): return Paragraph(str(text), styles[style])

    def header_footer(canvas, doc):
        canvas.saveState(); w, h = A4
        canvas.setFillColor(NAVY); canvas.rect(0, h - 8*mm, w, 8*mm, stroke=0, fill=1)
        canvas.setStrokeColor(BORDER); canvas.line(18*mm, 16*mm, w - 18*mm, 16*mm)
        canvas.setFont("Helvetica", 7); canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 10.5*mm, "EduPointAI  |  Your Education. Your Future.")
        canvas.drawRightString(w - 18*mm, 10.5*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=17*mm, bottomMargin=23*mm)
    story = []
    brand = Table([[P("EduPointAI", "Brand"), P("ADVANCED RESULTS REPORT", "WhiteSmall")]], colWidths=[75*mm, 99*mm], rowHeights=[22*mm])
    brand.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), NAVY), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 12), ("ALIGN", (1,0), (1,0), "RIGHT")]))
    story += [brand, Spacer(1, 8*mm)]

    story += [P("Your academic assessment is ready", "HeroTitle"), P("Personalized overview of your performance and opportunities.", "Sub"), Spacer(1, 5*mm)]
    today = datetime.now().strftime("%d %b %Y")
    ref = "EP-2026-" + ''.join(random.choices(string.digits, k=6))
    student = Table([[P("STUDENT", "Tiny"), P("REPORT REFERENCE", "Tiny")], [P(user_name, "BodySmall"), P(ref, "BodySmall")]], colWidths=[87*mm, 87*mm])
    student.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PALE), ("BOX", (0,0), (-1,-1), 0.7, BORDER), ("INNERGRID", (0,0), (-1,-1), 0.5, BORDER), ("LEFTPADDING", (0,0), (-1,-1), 9), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
    story += [student, Spacer(1, 5*mm)]

    qualified = [r for r in results if r['match'] == 'qualified']
    close = [r for r in results if r['match'] == 'close']
    cards = Table([[P("CLUSTER POINTS", "CardLabel"), P("QUALIFIED COURSES", "CardLabel"), P("CLOSE MATCHES", "CardLabel")], [P(str(cluster_points), "CardValue"), P(str(len(qualified)), "CardValue"), P(str(len(close)), "CardValue")]], colWidths=[58*mm, 58*mm, 58*mm])
    cards.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), LIGHT_BLUE), ("BACKGROUND", (1,0), (1,-1), LIGHT_PURPLE), ("BACKGROUND", (2,0), (2,-1), PALE), ("BOX", (0,0), (-1,-1), 0.6, BORDER), ("INNERGRID", (0,0), (-1,-1), 1, colors.white), ("LEFTPADDING", (0,0), (-1,-1), 10), ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
    story += [cards, Spacer(1, 5*mm)]

    story += [P("01  Academic profile", "Section")]
    grades_data = [[P("SUBJECT", "Tiny"), P("GRADE", "Tiny"), P("POINTS", "Tiny")]]
    for i in range(7):
        subj = subjects.get(str(i), f"Subject {i+1}")
        grade = grades.get(str(i), "-")
        pts = W.get(grade.upper(), 0) if grade else 0
        grades_data.append([P(subj, "BodySmall"), P(grade, "BodySmall"), P(str(pts), "BodySmall")])
    gt = Table(grades_data, colWidths=[100*mm, 37*mm, 37*mm])
    gt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), PALE), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("LEFTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
    story += [gt, Spacer(1, 5*mm)]

    story.append(PageBreak())
    story += [P("02  Course Matching Analysis", "Section")]
    if qualified:
        course_data = [[P("COURSE", "Tiny"), P("INSTITUTION", "Tiny"), P("CUTOFF", "Tiny"), P("GAP", "Tiny")]]
        for c in qualified[:15]: course_data.append([P(c['n'], "BodySmall"), P(c['u'], "BodySmall"), P(str(c['c']), "BodySmall"), P(f"+{c['difference']:.3f}", "BodySmall")])
        ct = Table(course_data, colWidths=[70*mm, 50*mm, 25*mm, 29*mm])
        ct.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), LIGHT_BLUE), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("LEFTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        story += [ct, Spacer(1, 4*mm)]

    if close:
        story += [P("Close Matches", "Section")]
        close_data = [[P("COURSE", "Tiny"), P("INSTITUTION", "Tiny"), P("CUTOFF", "Tiny"), P("GAP", "Tiny")]]
        for c in close[:10]: close_data.append([P(c['n'], "BodySmall"), P(c['u'], "BodySmall"), P(str(c['c']), "BodySmall"), P(f"{c['difference']:.3f}", "BodySmall")])
        clt = Table(close_data, colWidths=[70*mm, 50*mm, 25*mm, 29*mm])
        clt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), HexColor("#FEF3C7")), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("LEFTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        story += [clt, Spacer(1, 5*mm)]

    story.append(PageBreak())
    story += [P("03  Scholarship Opportunities", "Section")]
    sch_data = [[P("SCHOLARSHIP", "Tiny"), P("AMOUNT", "Tiny"), P("LINK", "Tiny")]]
    for s in scholarships[:8]: sch_data.append([P(s['name'], "BodySmall"), P(s['amount'], "BodySmall"), P(s['link'], "BodySmall")])
    st = Table(sch_data, colWidths=[65*mm, 45*mm, 64*mm])
    st.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), LIGHT_PURPLE), ("GRID", (0,0), (-1,-1), 0.45, BORDER), ("LEFTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story += [st]

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    buffer.seek(0)
    return buffer

def send_pdf_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships, payment=None):
    try:
        # 1. Generate Results PDF
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        
        attachments = [{"content": pdf_base64, "name": "EduPointAI_Results.pdf"}]

        # 2. Generate Invoice PDF (if payment is provided)
        if payment:
            inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
            inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode('utf-8')
            attachments.append({"content": inv_base64, "name": f"Invoice_{payment['transaction_id']}.pdf"})

        api_key = os.getenv("BREVO_API_KEY"); sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return
        
        client = Brevo(api_key=api_key)
        
        html = f"""
        <div style='font-family: Arial;'>
            <h2>Dear {user_name},</h2>
            <p>Your payment is confirmed and your assessment is complete.</p>
            <p>Cluster Points: <b>{cluster_points}</b></p>
            <p>Please find attached your official Results Report and your Payment Invoice/Receipt.</p>
            <p>EduPointAI Team</p>
        </div>
        """
        
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Results & Invoice",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=attachments
        )
        logger.info(f"Successfully sent results and invoice to {user_email}")
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
            # 1. Process calculation
            calc_results = process_calculation(u, row["calculation_data"]["subjects"], row["calculation_data"]["grades"])
            
            # 2. Send Email with Results + Invoice
            threading.Thread(
                target=send_pdf_email, 
                args=(u["email"], u["name"], calc_results["cluster_points"], calc_results["results"], 
                      row["calculation_data"]["subjects"], row["calculation_data"]["grades"], SCHOLARSHIPS, row)
            ).start()

            # 3. Clear calculation data to prevent duplicates
            payments.update(transaction_id, calculation_data=None)
        except Exception as e:
            logger.error(f"Calculation failed post-payment: {e}")

    return jsonify(ok=True, payment=row, calculation_results=calc_results)

@app.get("/api/invoice/<transaction_id>")
@login_required
def download_invoice(transaction_id):
    u = current_user()
    row = payments.get(transaction_id)
    if not row or row["user_id"] != u["id"]:
        return jsonify(ok=False, error="Invoice not found"), 404
        
    pdf_buffer = generate_invoice_pdf(u, row)
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=f"Invoice_{transaction_id}.pdf")

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


# ==========================================
# CRON JOB ROUTE (Keep at the bottom!)
# ==========================================
@app.get("/api/cron/daily-reports")
def trigger_daily_reports():
    secret = request.args.get("secret")
    expected_secret = os.getenv("CRON_SECRET", "edupoint_secret_123")
    
    if secret != expected_secret:
        return jsonify(ok=False, error="Unauthorized"), 401
        
    success = generate_and_send_reports()
    if success:
        return jsonify(ok=True, message="Reports generated and emailed successfully.")
    else:
        return jsonify(ok=False, error="Failed to generate reports."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
