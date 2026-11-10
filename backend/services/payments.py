import os, re, time, logging, requests, json
from datetime import datetime
from db import connect

logger = logging.getLogger(__name__)

ALLOWED = {"pesapal"}

PROVIDER_CATALOG = {
    "pesapal": {"id": "pesapal", "name": "Pesapal (M-PESA, Airtel, T-Kash, Card)", "description": "Secure checkout."}
}

def normalize_phone(phone):
    p = re.sub(r"\D", "", str(phone or ""))
    if p.startswith("254") and len(p) == 12: return p
    if p.startswith("0") and len(p) == 10: return "254" + p[1:]
    if len(p) == 9 and p.startswith("7"): return "254" + p
    return None

def validate_provider(p):
    return p in ALLOWED

class PaymentService:
    def __init__(self):
        self._status_checked = {}

    def create_pending(self, transaction_id, user_id, phone, network, amount, plan, calculation_data=None):
        with connect() as conn:
            conn.execute(
                """INSERT INTO payments(transaction_id, user_id, phone, network, amount, plan, status, message, calculation_data, created_at, updated_at)
                   VALUES(%s, %s, %s, %s, %s, %s, 'pending', 'Waiting for payment', %s, now(), now())""",
                (transaction_id, user_id, phone, network, amount, plan, json.dumps(calculation_data) if calculation_data else None)
            )

    def update(self, tx, status=None, provider_reference=None, message=None, redirect_url=None, calculation_data="KEEP"):
        fields, vals = [], []
        if status is not None: fields.append("status=%s"); vals.append(status)
        if provider_reference is not None: fields.append("provider_reference=%s"); vals.append(provider_reference)
        if message is not None: fields.append("message=%s"); vals.append(message)
        if redirect_url is not None: fields.append("redirect_url=%s"); vals.append(redirect_url)
        if calculation_data != "KEEP": fields.append("calculation_data=%s"); vals.append(calculation_data)
        
        fields.append("updated_at=now()")
        vals.append(tx)
        
        with connect() as conn:
            conn.execute(f"UPDATE payments SET {','.join(fields)} WHERE transaction_id=%s", vals)

    def get(self, tx):
        with connect() as conn:
            row = conn.execute("SELECT * FROM payments WHERE transaction_id=%s", (tx,)).fetchone()
        return row

    def initiate(self, provider, phone, amount, transaction_id, plan, user, callback_url):
        if provider == "pesapal":
            return self.pesapal_collection(transaction_id, amount, plan, phone, user, callback_url)
        raise ValueError("Unsupported provider")

    def ensure_pesapal_ipn(self, client):
        # Using the IPN registered in your Pesapal dashboard
        return os.getenv("PESAPAL_IPN_ID", "")

    def pesapal_collection(self, tx, amount, plan, phone, user, callback_url):
        from .pesapal import PesapalClient
        client = PesapalClient()
        if not client.configured:
            raise RuntimeError("Pesapal is not configured.")
        
        ipn_id = self.ensure_pesapal_ipn(client)
        full = (user.get("name") or "EduPoint Student").strip()
        first, _, last = full.partition(" ")

        order = client.submit_order(
            merchant_reference=tx,
            amount=amount,
            currency=os.getenv("PESAPAL_CURRENCY", "KES"),
            description=f"EduPoint AI - {plan} plan",
            callback_url=callback_url,
            ipn_id=ipn_id,
            email=user.get("email") or "student@edupoint.local",
            phone=phone,
            first_name=first or "EduPoint",
            last_name=last or "Student",
        )
        return {
            "status": "pending",
            "provider_reference": order["order_tracking_id"],
            "redirect_url": order["redirect_url"],
            "message": "Redirecting to Pesapal checkout..."
        }

    def check_status(self, row):
        if row.get("network") != "pesapal": return None
        tracking = row.get("provider_reference")
        if not tracking: return None
        
        ttl = float(os.getenv("PESAPAL_STATUS_TTL", "5"))
        now = time.monotonic()
        last = self._status_checked.get(row["transaction_id"])
        if last and now - last < ttl: return None
        self._status_checked[row["transaction_id"]] = now

        from .pesapal import PesapalClient, PesapalError
        try:
            st = PesapalClient().transaction_status(tracking)
        except PesapalError:
            return None

        status = {1: "paid", 2: "failed", 3: "reversed", 0: "invalid"}.get(st.get("status_code"), "pending")
        return {"status": status, "message": st.get("status") or ""}
