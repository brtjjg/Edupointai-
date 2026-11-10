#!/usr/bin/env python3
import os
import uuid
import logging
import base64
import threading
import random
import string
import io
import json
from datetime import datetime

import psycopg
from flask import Flask, request, jsonify
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

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["JSON_SORT_KEYS"] = False

FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGINS}}, allow_headers=["Content-Type", "Authorization"], methods=["GET", "POST", "DELETE", "OPTIONS"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
payments = PaymentService()

# --- HELPER FUNCTIONS ---

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

def process_calculation(u, subjects, grades, is_paid=False):
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
        if not is_paid:
            conn.execute("UPDATE users SET credits = credits - 1 WHERE id=%s", (u["id"],))
            
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
                
    # Send email
    threading.Thread(
        target=send_pdf_email, 
        args=(u["email"], u["name"], round(cp, 3), out, subjects, grades, SCHOLARSHIPS)
    ).start()
    
    return {"reference": ref_code, "cluster_points": round(cp, 3), "results": out}

# --- PDF & EMAIL GENERATION ---
def send_pdf_email(user_email, user_name, cluster_points, results, subjects, grades, scholarships):
    try:
        # ... [Keep your existing PDF generation logic here] ...
        # For brevity, assuming generate_report_pdf returns a BytesIO buffer
        pdf_buffer = generate_report_pdf(user_name, user_email, cluster_points, results, subjects, grades, scholarships)
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')

        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")
        if not api_key or not sender_email: return

        client = Brevo(api_key=api_key)
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
                </ul>
            </div>
            <p>Please find your detailed PDF report attached.</p>
            <br>
            <p>Kind regards,</p>
            <p><b>EduPointAI Team</b></p>
        </div>
        """

        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Calculation Report",
            html_content=email_html,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user_email, name=user_name)],
            attachment=[{"content": pdf_base64, "name": "EduPointAI_Results_Report.pdf"}]
        )
        logger.info(f"Email successfully sent to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


# --- ROUTES ---

@app.get("/health")
def health(): return jsonify(ok=True, service="edupoint-api")

@app.post("/api/auth/google")
def google_login():
    d = request.get_json(silent=True) or {}
    token = d.get("credential")
    if not token: return jsonify(ok=False, error="No Google credential provided."), 400
        
    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), os.getenv("GOOGLE_CLIENT_ID"))
        email = idinfo["email"].strip().lower()
        name = idinfo.get("name", "Google User")
        
        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            if not u:
                u = conn.execute(
                    """INSERT INTO users(name, email, phone, password_hash, role, credits) 
                       VALUES(%s, %s, %s, %s, 'student', 0) RETURNING *""", 
                    (name, email, "0700000000", "GOOGLE_AUTH")
                ).fetchone()
                
        session_token = create_session(u["id"])
        return jsonify(ok=True, token=session_token, user=public_user(u), redirect="/")
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
    return jsonify(ok=True, user=public_user(u), credits=u.get("credits", 0))

@app.post("/api/payment/initiate")
@login_required
def initiate_payment():
    u = current_user()
    d = request.get_json(silent=True) or {}
    provider = (d.get("provider") or "").strip().lower()
    phone = normalize_phone(d.get("phone") or u["phone"])
    plan = (d.get("plan") or "standard").strip().lower()
    
    subjects = d.get("subjects")
    grades = d.get("grades")
    calc_data = {"subjects": subjects, "grades": grades} if subjects and grades else None

    if plan not in PAYMENT_PLANS: return jsonify(ok=False, error="Invalid payment plan."), 400
    if not validate_provider(provider): return jsonify(ok=False, error="Unsupported payment network."), 400
    if not phone: return jsonify(ok=False, error="Enter a valid Kenyan mobile number."), 400

    amount = PAYMENT_PLANS[plan]["amount"]
    tx = "EDU-" + uuid.uuid4().hex[:16].upper()
    callback_url = f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/"
    
    with connect() as conn:
        conn.execute(
            """INSERT INTO payments(transaction_id, user_id, phone, network, amount, plan, status, message, calculation_data, created_at, updated_at)
               VALUES(%s, %s, %s, %s, %s, %s, 'pending', 'Waiting for payment', %s, now(), now())""",
            (tx, u["id"], phone, provider, amount, plan, json.dumps(calc_data) if calc_data else None)
        )
    
    try:
        r = payments.initiate(provider=provider, phone=phone, amount=amount, transaction_id=tx, plan=plan, user=u, callback_url=callback_url)
        payments.update(tx, status=r.get("status", "pending"), provider_reference=r.get("provider_reference"), message=r.get("message"), redirect_url=r.get("redirect_url"))
        return jsonify(ok=True, transaction_id=tx, status=r.get("status", "pending"), message=r.get("message"), redirect_url=r.get("redirect_url"))
    except Exception:
        payments.update(tx, status="failed", message="Payment could not be started.")
        return jsonify(ok=False, error="Payment could not be started."), 502

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
        except Exception: pass

    calc_results = None
    if row["status"] == "paid" and row.get("user_id"):
        add_credit(row["user_id"])
        payments.update(transaction_id, status="completed")
        row["status"] = "completed"
        
        if row.get("calculation_data"):
            try:
                with connect() as conn:
                    fresh_u = conn.execute("SELECT * FROM users WHERE id=%s", (u["id"],)).fetchone()
                calc_results = process_calculation(fresh_u, row["calculation_data"]["subjects"], row["calculation_data"]["grades"], is_paid=True)
                payments.update(transaction_id, calculation_data=None)
            except Exception as e:
                logger.error(f"Failed to process calculation: {e}")

    return jsonify(ok=True, payment=row, calculation_results=calc_results)

@app.get("/api/history")
@login_required
def get_history():
    u = current_user()
    with connect() as conn:
        rows = conn.execute(
            """SELECT h.*, 
               (SELECT COUNT(*) FROM calculation_courses WHERE history_id = h.id AND match_type = 'qualified') as qual_count
               FROM calculation_history h WHERE h.user_id = %s ORDER BY h.created_at DESC""", (u["id"],)
        ).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["cluster_points"] = float(r["cluster_points"])
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
