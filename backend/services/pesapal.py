import os, time, logging, requests

logger = logging.getLogger(__name__)


class PesapalError(RuntimeError):
    pass


class PesapalClient:
    SANDBOX = "https://cybqa.pesapal.com/pesapalv3"
    PRODUCTION = "https://pay.pesapal.com/v3"

    def __init__(self, consumer_key=None, consumer_secret=None,
                 base_url=None, env=None, timeout=30):
        self.consumer_key = (consumer_key or os.getenv("PESAPAL_CONSUMER_KEY", "")).strip()
        self.consumer_secret = (consumer_secret or os.getenv("PESAPAL_CONSUMER_SECRET", "")).strip()
        env = (env or os.getenv("PESAPAL_ENV", "sandbox")).strip().lower()
        default = self.PRODUCTION if env == "production" else self.SANDBOX
        self.base_url = (base_url or os.getenv("PESAPAL_BASE_URL") or default).rstrip("/")
        self.timeout = timeout
        self._token = None
        self._token_expiry = 0.0

    @property
    def configured(self):
        return bool(self.consumer_key and self.consumer_secret)

    def _request(self, method, path, **kw):
        url = f"{self.base_url}{path}"
        r = requests.request(method, url, timeout=self.timeout, **kw)
        if not r.ok:
            raise PesapalError(f"Pesapal {method} {path} -> {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            raise PesapalError(f"Pesapal {path} returned non-JSON: {r.text[:300]}")

    def token(self):
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        data = self._request(
            "POST", "/api/Auth/RequestToken",
            json={"consumer_key": self.consumer_key, "consumer_secret": self.consumer_secret},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        tok = data.get("token")
        if not tok:
            raise PesapalError(f"Pesapal auth returned no token: {data}")
        self._token = tok
        self._token_expiry = time.time() + float(data.get("expiryDateInSeconds") or 300)
        return tok

    def _headers(self):
        return {
            "Authorization": "Bearer " + self.token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # Find your PesapalClient class and ensure this method is inside it:
def register_ipn(self, url, notification_type="GET"):
    data = self._request(
        "POST", "/api/URLSetup/RegisterIPN",
        json={"url": url, "ipn_notification_type": notification_type},
        headers=self._headers(),
    )
    ipn_id = data.get("ipn_id")
    if not ipn_id:
        raise PesapalError(f"Pesapal RegisterIPN failed: {data}")
    return ipn_id

    def submit_order(self, *, merchant_reference, amount, currency, description,
                     callback_url, ipn_id, email, phone, first_name, last_name,
                     country_code="KE"):
        payload = {
            "id": merchant_reference,
            "currency": currency,
            "amount": float(amount),
            "description": description,
            "callback_url": callback_url,
            "notification_id": ipn_id,
            "billing_address": {
                "email_address": email,
                "phone_number": phone,
                "country_code": country_code,
                "first_name": first_name,
                "last_name": last_name,
            },
        }
        data = self._request("POST", "/api/Transactions/SubmitOrderRequest",
                             json=payload, headers=self._headers())
        tracking = data.get("order_tracking_id")
        redirect = data.get("redirect_url")
        if not tracking or not redirect:
            raise PesapalError(f"Pesapal order rejected: {data}")
        return {"order_tracking_id": tracking,
                "redirect_url": redirect,
                "merchant_reference": data.get("merchant_reference", merchant_reference)}

    def transaction_status(self, order_tracking_id):
        data = self._request(
            "GET", "/api/Transactions/GetTransactionStatus",
            params={"orderTrackingId": order_tracking_id},
            headers=self._headers(),
        )
        try:
            code = int(data.get("status_code", -1))
        except (TypeError, ValueError):
            code = -1
        return {
            "status_code": code,
            "status": data.get("payment_status_description") or "",
            "amount": data.get("amount"),
            "currency": data.get("currency"),
            "merchant_reference": data.get("merchant_reference"),
            "confirmation_code": data.get("confirmation_code"),
            "payment_method": data.get("payment_method"),
            "raw": data,
        }
