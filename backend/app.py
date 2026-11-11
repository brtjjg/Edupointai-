#!/usr/bin/env python3
import os, uuid, logging, base64, threading, random, string, io, json, traceback
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

from data import W, BEST, MAX, P, SCHOLARSHIPS, PAYMENT_PLANS
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
# PDF & EMAIL GENERATION
# ==========================================

def generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships):
    # [Keep your existing generate_report_pdf logic here]
    # ... (No changes needed to the results PDF)
    pass # (I am omitting the long code here for brevity, keep your existing function)

def send_pending_invoice_email(user_email, user_name, payment):
    """Sends an invoice email with a PENDING status when the user clicks Pay."""
    try:
        # payment dict has status='pending' at this point, so the PDF will render as PENDING
        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode('utf-8')
        
        api_key = os.getenv("BREVO_API_KEY"); sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return
        
        client = Brevo(api_key=api_key)
        html = f"""
        <div style='font-family: Arial;'>
            <h2>Dear {user_name},</h2>
            <p>Your payment has been initiated. Please find your pending invoice attached.</p>
            <p>Complete the payment on the Pesapal page to unlock your results. Once paid, you will receive a final Receipt and your Results Report.</p>
            <p>EduPointAI Team</p>
        </div>
        """
        
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Pending Invoice",
            html_content=html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": inv_base64, "name": f"Pending_Invoice_{payment['transaction_id']}.pdf"}]
        )
        logger.info(f"Sent pending invoice to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send pending invoice: {e}")

def send_paid_receipt_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships, payment):
    """Sends the final PAID receipt + Results when payment succeeds."""
    try:
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        
        attachments = [{"content": pdf_base64, "name": "EduPointAI_Results.pdf"}]

        # payment dict has status='completed' now, so the PDF will render as PAID
        inv_buffer = generate_invoice_pdf({"name": user_name, "email": user_email, "id": payment.get("user_id")}, payment)
        inv_base64 = base64.b64encode(inv_buffer.getvalue()).decode('utf-8')
        attachments.append({"content": inv_base64, "name": f"Receipt_{payment['transaction_id']}.pdf"})

        api_key = os.getenv("BREVO_API_KEY"); sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return
        
        client = Brevo(api_key=api_key)
        html = f"""
        <div style='font-family: Arial;'>
            <h2>Dear {user_name},</h2>
            <p>Your payment is confirmed and your assessment is complete.</p>
            <p>Cluster Points: <b>{cluster_points}</b></p>
            <p>Please find attached your official Results Report and your Payment Receipt.</p>
            <p>EduPointAI Team</p>
        </div>
        """
        
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
        
        # --- NEW: Send the Pending Invoice immediately ---
        pending_payment = payments.get(tx)
        threading.Thread(target=send_pending_invoice_email, args=(u["email"], u["name"], pending_payment)).start()
        # -------------------------------------------------

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
            
            # Send the Final PAID Receipt + Results
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

@app.post("/api/chat")
@login_required
def chat():
    d = request.get_json(silent=True) or {}
    question = str(d.get("question", "")).lower().strip()
    
    if not question: 
        return jsonify(answer="Ask me about any career, course, or subject requirement!")

    # 1. Clean the question (Remove common stop words to improve matching)
    stop_words = {"what", "is", "a", "an", "the", "can", "i", "do", "with", "to", "for", "in", "of", "and", "how", "which", "are", "my", "me"}
    words = [w for w in re.findall(r'\b\w+\b', question) if w not in stop_words]
    
    # 2. Score all knowledge base entries
    best_match = None
    highest_score = 0

    for qa in CHATBOT_QA:
        score = 0
        # Score based on keyword matches
        for kw in qa["keywords"]:
            kw_words = kw.lower().split()
            # If the exact phrase is in the question, huge boost
            if kw in question:
                score += 10
            else:
                # Otherwise, check individual word overlap
                for kw_word in kw_words:
                    if kw_word in words:
                        score += 2
        
        if score > highest_score:
            highest_score = score
            best_match = qa

    # 3. Return the best match (if score is above a threshold)
    if best_match and highest_score >= 2:
        return jsonify(answer=best_match["answer"])

    # 4. Fallback if no good match is found
    return jsonify(answer="I am still expanding my career database. Try asking about specific careers (e.g., 'Software Engineer', 'Nursing'), subject requirements, or KCSE grades.")

@app.get("/api/cron/daily-reports")
def trigger_daily_reports():
    secret = request.args.get("secret")
    expected_secret = os.getenv("CRON_SECRET", "edupoint_secret_123")
    if secret != expected_secret: return jsonify(ok=False, error="Unauthorized"), 401
    success = generate_and_send_reports()
    return jsonify(ok=True, message="Reports generated.") if success else jsonify(ok=False), 500

@app.get("/api/test-invoice")
def test_invoice():
    u = {"name": "Brian Ondieki", "email": "brayondueki815@gmail.com", "id": 2}
    payment = {
        "transaction_id": "EDU-TEST123456",
        "user_id": 2,
        "amount": 100,
        "status": "pending",
        "created_at": datetime.now()
    }
    # Send email
    send_pending_invoice_email(u["email"], u["name"], payment)
    return jsonify(ok=True, message="Test invoice triggered! Check logs and Gmail.")

# ==========================================
# GLOBAL ERROR HANDLERS (Add before if __name__)
# ==========================================

@app.errorhandler(404)
def not_found_error(error):
    return jsonify(ok=False, error="The requested resource was not found."), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    return jsonify(ok=False, error="Method not allowed."), 405

@app.errorhandler(500)
def internal_error(error):
    # Log the actual error to Render logs for debugging
    logger.error(f"Internal Server Error: {traceback.format_exc()}")
    return jsonify(ok=False, error="A system error occurred. Please try again later."), 500

@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP errors (like 401 Unauthorized)
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description), e.code
    
    # Log the actual Python error to Render logs
    logger.error(f"Unhandled Exception: {traceback.format_exc()}")
    
    # Return a safe message to the user
    return jsonify(ok=False, error="An unexpected error occurred. Please contact support."), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
