# services/reminders.py
import logging
from db import connect
from services.invoices import send_invoice_reminder_email

logger = logging.getLogger(__name__)

def send_daily_reminders():
    """Finds pending payments and emails reminders. Run this via a daily Cron Job."""
    logger.info("Starting daily invoice reminders...")
    
    try:
        with connect() as conn:
            # Fetch payments that are still pending and created more than 12 hours ago
            # (so we don't spam someone who just initiated payment 1 minute ago)
            query = """
                SELECT p.transaction_id, p.user_id, p.amount, p.status, p.redirect_url, p.created_at,
                       u.name, u.email
                FROM payments p
                JOIN users u ON u.id = p.user_id
                WHERE p.status = 'pending' 
                AND p.created_at <= NOW() - INTERVAL '12 hours'
            """
            pending_payments = conn.execute(query).fetchall()

        if not pending_payments:
            logger.info("No pending payments found for reminders.")
            return

        success_count = 0
        for row in pending_payments:
            user = {"name": row["name"], "email": row["email"]}
            payment = {
                "transaction_id": row["transaction_id"],
                "amount": row["amount"],
                "status": row["status"],
                "redirect_url": row["redirect_url"],
                "created_at": row["created_at"]
            }
            
            # Send the reminder
            sent = send_invoice_reminder_email(
                user=user,
                payment=payment,
                payment_link=row["redirect_url"]
            )
            if sent:
                success_count += 1

        logger.info(f"Reminders sent successfully: {success_count} out of {len(pending_payments)}")

    except Exception as e:
        logger.error(f"Error sending daily reminders: {e}")

if __name__ == "__main__":
    # This block allows you to run it directly for testing: python -m services.reminders
    logging.basicConfig(level=logging.INFO)
    send_daily_reminders()
