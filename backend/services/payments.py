import os, re, time, logging, requests
from datetime import datetime, timezone

from db import connect
from .pesapal import PesapalClient, PesapalError

logger = logging.getLogger(__name__)

ALLOWED = {"pesapal", "airtel", "tkash"}

PROVIDER_CATALOG = {
    "pesapal": {"id": "pesapal",
                "name": "Pesapal (M-PESA, Airtel, T-Kash, Card)",
                "description": "Secure hosted checkout — choose your method on the Pesapal page."},
    "airtel": {"id": "airtel", "name": "Airtel Money",
               "description": "Pay using an Airtel Money number."},
    "tkash": {"id": "tkash", "name": "T-Kash", "description": "Pay using T-Kash."},
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

    # ---------------- settings ----------------
    def _get_setting(self, key):
        with connect() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return r["value"] if r else None

    def _set_setting(self, key, value):
        with connect() as conn:
            conn.execute(
                """INSERT INTO settings(key,value) VALUES(%s,%s)
                   ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""",
                (key, value),
            )

    # ---------------- providers ----------------
    def available_providers(self):
        want = [p.strip().lower() for p in
                os.getenv("PAYMENTS_PROVIDERS", "pesapal").split(",") if p.strip()]
        out = []
        for pid in want:
            if pid == "pesapal" and not PesapalClient().configured:
                logger.warning("Pesapal enabled but credentials missing.")
                continue
            if pid in PROVIDER_CATALOG:
                out.append(PROVIDER_CATALOG[pid])
        return out

    # ---------------- payments ----------------
    def create_pending(self, **kw):
        with connect() as conn:
            conn.execute(
                """INSERT INTO payments(transaction_id,user_id,phone,network,
                   amount,plan,status,message) VALUES(%s,%s,%s,%s,%s,%s,'pending',%s)""",
                (kw["transaction_id"], kw.get("user_id"), kw["phone"], kw["network"],
                 kw["amount"], kw["plan"], "Waiting for payment"),
            )

    def update(self, tx, status=None, provider_reference=None, message=None, redirect_url=None):
        fields, vals = [], []
        for name, val in (("status", status), ("provider_reference", provider_reference),
                          ("message", message), ("redirect_url", redirect_url)):
            if val is not None:
                fields.append(f"{name}=%s")
                vals.append(val)
        fields.append("updated_at=now()")
        vals.append(tx)
        with connect() as conn:
            conn.execute("UPDATE payments SET " + ",".join(fields) + " WHERE transaction_id=%s", vals)

    def get(self, tx):
        with connect() as conn:
            r = conn.execute("SELECT * FROM payments WHERE transaction_id=%s", (tx,)).fetchone()
        return r

    def get_by_reference(self, provider_reference):
        with connect() as conn:
            r = conn.execute("SELECT * FROM payments WHERE provider_reference=%s",
                             (provider_reference,)).fetchone()
        return r

    # ---------------- dispatch ----------------
    def initiate(self, provider, phone, amount, transaction_id, plan, user=None, callback_url=None):
        if provider == "airtel":
            return self.airtel_collection(phone, amount, transaction_id)
        if provider == "tkash":
            return self.tkash_collection(phone, amount, transaction_id, plan)
        if provider == "pesapal":
            return self.pesapal_collection(transaction_id, amount, plan, phone, user or {}, callback_url)
        raise ValueError("Unsupported provider")

    # ---------------- pesapal ----------------
    def ensure_pesapal_ipn(self, client=None):
        client = client or PesapalClient()
        cached = os.getenv("PESAPAL_IPN_ID", "").strip() or self._get_setting("pesapal_ipn_id")
        if cached:
            return cached
        url = os.getenv("PESAPAL_IPN_URL", "").strip()
        if not url:
            base = os.getenv("BACKEND_URL", "").rstrip("/")
            if not base:
                raise RuntimeError("Set BACKEND_URL or PESAPAL_IPN_URL so Pesapal can reach your IPN endpoint.")
            url = base + "/api/payment/webhook/pesapal"
        ipn_id = client.register_ipn(url)
        self._set_setting("pesapal_ipn_id", ipn_id)
        logger.info("Registered Pesapal IPN %s -> %s", ipn_id, url)
        return ipn_id

    def pesapal_collection(self, tx, amount, plan, phone, user, callback_url):
        client = PesapalClient()
        if not client.configured:
            raise RuntimeError("Pesapal is not configured.")
        if not callback_url:
            raise RuntimeError("callback_url is required for Pesapal.")

        ipn_id = self.ensure_pesapal_ipn(client)
        full = (user.get("name") or "EduPoint Student").strip()
        first, _, last = full.partition(" ")

        order = client.submit_order(
            merchant_reference=tx,
            amount=amount,
            currency=os.getenv("PESAPAL_CURRENCY", "KES"),
            description=f"EduPoint AI — {plan} plan",
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
            "message": "Redirecting you to the Pesapal checkout…",
            "instructions": ["Complete the payment on the Pesapal page."],
        }

    def _map_pesapal(self, row, st):
        status = {1: "paid", 2: "failed", 3: "reversed", 0: "invalid"}.get(
            st.get("status_code"), "pending")
        if status == "paid":
            try:
                paid = float(st.get("amount") or 0)
            except (TypeError, ValueError):
                paid = 0.0
            if paid + 0.01 < float(row["amount"]):
                logger.warning("Pesapal amount mismatch on %s", row["transaction_id"])
                status = "amount_mismatch"
        return {"status": status, "message": st.get("status") or ""}

    def check_status(self, row):
        if row.get("network") != "pesapal":
            return None
        tracking = row.get("provider_reference")
        if not tracking:
            return None
        ttl = float(os.getenv("PESAPAL_STATUS_TTL", "8"))
        now = time.monotonic()
        last = self._status_checked.get(row["transaction_id"])
        if last and now - last < ttl:
            return None
        self._status_checked[row["transaction_id"]] = now
        try:
            st = PesapalClient().transaction_status(tracking)
        except PesapalError:
            logger.exception("Pesapal status check failed for %s", row["transaction_id"])
            return None
        return self._map_pesapal(row, st)

    def handle_pesapal_ipn(self, payload):
        tracking = str(payload.get("orderTrackingId")
                       or payload.get("ordertrackingid") or "").strip()
        ref = str(payload.get("orderMerchantReference")
                  or payload.get("ordermerchantreference") or "").strip()

        row = self.get(ref) if ref else None
        if not row and tracking:
            row = self.get_by_reference(tracking)
        if not row:
            return {"ok": False, "error": "Unknown transaction reference."}

        tracking = tracking or row.get("provider_reference")
        try:
            st = PesapalClient().transaction_status(tracking)
        except PesapalError:
            logger.exception("Pesapal IPN lookup failed")
            return {"ok": False, "error": "Status lookup failed."}

        mapped = self._map_pesapal(row, st)
        self.update(row["transaction_id"], status=mapped["status"],
                    provider_reference=tracking, message=mapped["message"])
        return {"ok": True, "transaction_id": row["transaction_id"], "status": mapped["status"]}

    # ---------------- airtel / tkash (unchanged) ----------------
    def airtel_collection(self, phone, amount, tx):
        base = os.getenv("AIRTEL_BASE_URL", "https://openapi.airtel.africa")
        token_url = os.getenv("AIRTEL_TOKEN_URL", base.rstrip("/") + "/auth/oauth2/token")
        pay_url = os.getenv("AIRTEL_PAYMENT_URL", base.rstrip("/") + "/merchant/v1/payments/")
        cid = os.getenv("AIRTEL_CLIENT_ID"); secret = os.getenv("AIRTEL_CLIENT_SECRET")
        country = os.getenv("AIRTEL_COUNTRY", "KE"); currency = os.getenv("AIRTEL_CURRENCY", "KES")
        if not cid or not secret:
            raise RuntimeError("Airtel API credentials are not configured.")
        tr = requests.post(token_url, json={"client_id": cid, "client_secret": secret,
                                            "grant_type": "client_credentials"},
                           headers={"Content-Type": "application/json"}, timeout=30)
        tr.raise_for_status()
        token = tr.json().get("access_token")
        if not token:
            raise RuntimeError("Airtel API did not return an access token.")
        payload = {"reference": tx,
                   "subscriber": {"country": country, "currency": currency, "msisdn": phone[-9:]},
                   "transaction": {"amount": amount, "country": country,
                                   "currency": currency, "id": tx}}
        r = requests.post(pay_url, json=payload,
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type": "application/json",
                                   "Accept": "application/json",
                                   "X-Country": country, "X-Currency": currency},
                          timeout=30)
        if not r.ok:
            raise RuntimeError(f"Airtel API error {r.status_code}: {r.text[:300]}")
        b = r.json()
        return {"status": "pending",
                "provider_reference": b.get("data", {}).get("transaction", {}).get("id") or tx,
                "message": "Airtel Money payment request sent."}

    def tkash_collection(self, phone, amount, tx, plan):
        endpoint = os.getenv("TKASH_COLLECTION_URL")
        key = os.getenv("TKASH_API_KEY")
        merchant = os.getenv("TKASH_MERCHANT_ID")
        if not endpoint or not key or not merchant:
            return {"status": "pending_manual", "provider_reference": tx,
                    "message": "T-Kash enabled, but business API credentials missing.",
                    "instructions": ["Use your T-Kash Paybill/Till.",
                                     "Use transaction reference: " + tx]}
        payload = {"merchant_id": merchant, "reference": tx, "amount": amount,
                   "phone": phone, "currency": "KES", "plan": plan,
                   "callback_url": os.getenv("BACKEND_URL", "").rstrip("/")
                                   + "/api/payment/webhook/tkash"}
        r = requests.post(endpoint, json=payload,
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"T-Kash API error {r.status_code}: {r.text[:300]}")
        b = r.json()
        return {"status": "pending",
                "provider_reference": b.get("transaction_id") or b.get("reference") or tx,
                "message": "T-Kash payment request created."}

    def handle_webhook(self, provider, payload):
        tx = (payload.get("transaction_id") or payload.get("transactionId")
              or payload.get("reference") or payload.get("external_reference"))
        status = str(payload.get("status") or payload.get("transaction_status")
                     or payload.get("state") or "").lower()
        if not tx:
            return {"ok": False, "error": "Missing transaction reference."}
        success = {"success", "successful", "completed", "paid", "successful_payment"}
        fail = {"failed", "failure", "cancelled", "canceled", "reversed"}
        final = "paid" if status in success else ("failed" if status in fail else "pending")
        pref = payload.get("provider_reference") or payload.get("receipt") or payload.get("transaction_id")
        self.update(tx, status=final, provider_reference=pref,
                    message=f"{provider} callback: {status or 'pending'}")
        return {"ok": True, "transaction_id": tx, "status": final}
