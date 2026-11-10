import os
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify

from db import connect

SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return salt + "$" + digest

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token,user_id,expires_at) VALUES(%s,%s,%s)",
            (token, user_id, expires),
        )
    return token

def destroy_session(token: str):
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=%s", (token,))

def bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    return token or None

def current_user():
    token = bearer_token()
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token=%s AND s.expires_at > now() AND u.active=1""",
            (token,),
        ).fetchone()
    return row

def public_user(u):
    return {
        "id": u["id"],
        "name": u["name"],
        "email": u["email"],
        "phone": u["phone"],
        "role": u["role"],
        "referral_code": u["referral_code"],
        "active": bool(u["active"]),
    }

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return jsonify(ok=False, error="Login required."), 401
        return fn(*a, **kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        u = current_user()
        if not u:
            return jsonify(ok=False, error="Login required."), 401
        if u["role"] != "admin":
            return jsonify(ok=False, error="Admin only."), 403
        return fn(*a, **kw)
    return wrapper
