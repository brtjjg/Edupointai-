#!/usr/bin/env python3
import os
import uuid
import logging
import base64
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from fpdf import FPDF

import psycopg
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

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

def send_pdf_email(user_email, user_name, cluster_points, qualified_count):
    try:
        # 1. Generate PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=16)
        pdf.cell(200, 10, txt="EduPoint AI - Results Report", ln=True, align='C')
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"Student: {user_name}", ln=True)
        pdf.cell(200, 10, txt=f"Cluster Points: {cluster_points}", ln=True)
        pdf.cell(200, 10, txt=f"Qualified Courses: {qualified_count}", ln=True)
        pdf_bytes = pdf.output()

        # 2. Convert PDF to Base64 (Required by Brevo)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # 3. Setup Brevo Client
        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")
        
        if not api_key or not sender_email:
            logger.warning("Brevo API key or Sender Email missing. Skipping email.")
            return

        client = Brevo(api_key=api_key)

        # 4. Send Email via Brevo
        client.transactional_emails.send_transac_email(
            subject="Your EduPoint AI Calculation Report",
            html_content="<p>Thank you for using EduPoint AI. Please find your calculation report attached.</p>",
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPoint AI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[
                {
                    "content": pdf_base64,
                    "name": "EduPoint_Report.pdf"
                }
            ]
        )
        logger.info(f"Email successfully sent to {user_email} via Brevo.")
        
    except Exception as e:
        logger.error(f"Failed to send email via Brevo: {e}")

@app.get("/health")
def health(): return jsonify(ok=True, service="edupoint-api")

@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    name, email, phone, password = str(d.get("name", "")).strip(), str(d.get("email", "")).strip().lower(), normalize_phone(d.get("phone", "")), str(d.get("password", ""))
    ref = str(d.get("referral_code") or "").strip().upper() or None

    if len(name) < 2: return jsonify(ok=False, error="Enter your full name."), 400
    if "@" not in email: return jsonify(ok=False, error="Enter a valid email address."), 400
    if not phone: return jsonify(ok=False, error="Enter a valid Kenyan mobile number."), 400
    if len(password) < 6: return jsonify(ok=False, error="Password must contain at least 6 characters."), 400

    try:
        with connect() as conn:
            row = conn.execute("""INSERT INTO users(name,email,phone,password_hash,referral_code,role) VALUES(%s,%s,%s,%s,%s,'student') RETURNING id""", (name, email, phone, hash_password(password), ref)).fetchone()
            uid = row["id"]
    except psycopg.errors.UniqueViolation:
        return jsonify(ok=False, error="An account with that email already exists."), 409

    token = create_session(uid)
    return jsonify(ok=True, token=token, redirect="/dashboard.html")

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    email, password = str(d.get("email", "")).strip().lower(), str(d.get("password", ""))
    with connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email=%s AND active=1", (email,)).fetchone()
    if not u or not verify_password(password, u["password_hash"]):
        return jsonify(ok=False, error="Incorrect email or password."), 401
    token = create_session(u["id"])
    return jsonify(ok=True, token=token, user=public_user(u), redirect="/admin.html" if u["role"] == "admin" else "/dashboard.html")

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
                u = conn.execute("""INSERT INTO users(name, email, phone, password_hash, role) VALUES(%s, %s, %s, %s, 'student') RETURNING *""", (name, email, "0700000000", "GOOGLE_AUTH")).fetchone()
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
    return jsonify(ok=True, user=public_user(u), paid=has_paid_access(u["id"]), credits=u.get("credits", 0))

@app.get("/api/plans")
def plans(): return jsonify(PAYMENT_PLANS)

@app.get("/api/providers")
def providers(): return jsonify(payments.available_providers())

@app.post("/api/payment/initiate")
@login_required
def initiate_payment():
    u = current_user()
    d = request.get_json(silent=True) or {}
    provider, phone, plan = (d.get("provider") or "").strip().lower(), normalize_phone(d.get("phone") or u["phone"]), (d.get("plan") or "standard").strip().lower()

    if plan not in PAYMENT_PLANS: return jsonify(ok=False, error="Invalid payment plan."), 400
    if not validate_provider(provider): return jsonify(ok=False, error="Unsupported payment network."), 400
    if not phone: return jsonify(ok=False, error="Enter a valid Kenyan mobile number."), 400

    amount, tx = PAYMENT_PLANS[plan]["amount"], "EDU-" + uuid.uuid4().hex[:16].upper()
    callback_url = f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/payment-callback.html"
    
    payments.create_pending(transaction_id=tx, phone=phone, network=provider, amount=amount, plan=plan, user_id=u["id"])
    try:
        r = payments.initiate(provider=provider, phone=phone, amount=amount, transaction_id=tx, plan=plan, user=u, callback_url=callback_url)
        payments.update(tx, status=r.get("status", "pending"), provider_reference=r.get("provider_reference"), message=r.get("message"), redirect_url=r.get("redirect_url"))
        return jsonify(ok=True, transaction_id=tx, status=r.get("status", "pending"), message=r.get("message", "Payment request created."), instructions=r.get("instructions", []), redirect_url=r.get("redirect_url"))
    except Exception:
        logger.exception("Payment initiation failed")
        payments.update(tx, status="failed", message="Payment could not be started.")
        return jsonify(ok=False, transaction_id=tx, error="Payment could not be started."), 502

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

    if row["status"] == "paid" and row.get("user_id"):
        add_credit(row["user_id"])
        payments.update(transaction_id, status="completed")
        row["status"] = "completed"

    return jsonify(ok=True, payment=row, credits=u.get("credits", 0))

@app.route("/api/payment/webhook/<provider>", methods=["GET", "POST"])
def payment_webhook(provider):
    if not validate_provider(provider): return jsonify(ok=False, error="Unsupported provider"), 404
    payload = (request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict())

    if provider == "pesapal":
        r = payments.handle_pesapal_ipn(payload)
        if r.get("ok"):
            row = payments.get(r["transaction_id"])
            if row and row.get("user_id") and row["status"] == "paid":
                add_credit(row["user_id"])
                payments.update(row["transaction_id"], status="completed")
        return jsonify({"orderNotificationType": payload.get("orderNotificationType", "IPNCHANGE"), "orderTrackingId": payload.get("orderTrackingId", ""), "orderMerchantReference": payload.get("orderMerchantReference", ""), "status": 200 if r.get("ok") else 500}), 200

    r = payments.handle_webhook(provider, payload)
    if not r.get("ok"): return jsonify(r), 400
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
    
    try:
        vals = [W[str(v).strip().upper()] for v in grades.values() if str(v).strip().upper() in W]
        vals = sorted(vals, reverse=True)[:7]
        if len(vals) < 7: return jsonify(ok=False, error="Enter at least 7 valid grades."), 400
        
        cp = (sum(vals) / BEST) * MAX
        out = []
        for course in P:
            diff = cp - course["c"]
            out.append({**course, "difference": round(diff, 3), "match": "qualified" if diff >= 0 else ("close" if diff >= -2 else "not_qualified")})
            
        qualified_count = len([x for x in out if x["match"] == "qualified"])
        
        with connect() as conn:
            conn.execute("UPDATE users SET credits = credits - 1 WHERE id=%s", (u["id"],))
            
        threading.Thread(target=send_pdf_email, args=(u["email"], u["name"], round(cp, 3), qualified_count)).start()
            
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
    if not q: return jsonify(answer="Ask me a KUCCPS, course, cluster-points or scholarship question.")
    for x in CHATBOT_QA:
        if any(k in q for k in x["keywords"]): return jsonify(answer=x["answer"])
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
        if not r: return jsonify(ok=False, error="User not found."), 404
        conn.execute("UPDATE users SET active=%s WHERE id=%s", (0 if r["active"] else 1, user_id))
    return jsonify(ok=True)

@app.post("/api/admin/access/<int:user_id>")
@admin_required
def admin_access(user_id):
    d = request.get_json(silent=True) or {}
    paid = str(d.get("paid", "1")).lower() in {"1", "true", "yes"}
    if paid: add_credit(user_id)
    return jsonify(ok=True, paid=paid)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
