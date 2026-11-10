import os
import logging
from db import connect

logger = logging.getLogger(__name__)

class PaymentService:
    # ... [Keep your existing __init__ and other methods] ...

    def ensure_pesapal_ipn(self, client):
        # 1. Check if we already saved it in the database
        try:
            with connect() as conn:
                row = conn.execute("SELECT value FROM settings WHERE key='pesapal_ipn_id'").fetchone()
                if row and row['value']:
                    return row['value']
        except Exception as e:
            logger.error(f"DB check for IPN failed: {e}")

        # 2. Check if it's in the Render Environment Variables
        env_id = os.getenv("PESAPAL_IPN_ID", "").strip()
        if env_id:
            # Save it to DB for faster access next time
            try:
                with connect() as conn:
                    conn.execute("INSERT INTO settings (key, value) VALUES ('pesapal_ipn_id', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (env_id,))
            except Exception:
                pass
            return env_id

        # 3. If we don't have it, register it automatically with Pesapal
        base_url = os.getenv("BACKEND_URL", "https://edupoint-api.onrender.com").rstrip("/")
        ipn_url = f"{base_url}/api/payment/webhook/pesapal"
        
        logger.info(f"Auto-registering new IPN URL: {ipn_url}")
        ipn_id = client.register_ipn(ipn_url)
        
        # 4. Save the new ID to the database
        with connect() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES ('pesapal_ipn_id', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (ipn_id,))
            
        logger.info(f"Successfully registered IPN ID: {ipn_id}")
        return ipn_id

    def pesapal_collection(self, tx, amount, plan, phone, user, callback_url):
        from .pesapal import PesapalClient
        client = PesapalClient()
        if not client.configured:
            raise RuntimeError("Pesapal is not configured.")
        
        # This will now fetch or automatically create a valid IPN ID
        ipn_id = self.ensure_pesapal_ipn(client)
        
        full = (user.get("name") or "EduPoint Student").strip()
        first, _, last = full.partition(" ")

        order = client.submit_order(
            merchant_reference=tx,
            amount=amount,
            currency=os.getenv("PESAPAL_CURRENCY", "KES"),
            description=f"EduPoint AI - {plan} plan",
            callback_url=callback_url,
            ipn_id=ipn_id, # Now guaranteed to be a valid UUID
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
