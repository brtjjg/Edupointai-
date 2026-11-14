# EduPoint AI — Production (Pesapal)

Split deployment:
- **Backend** → Render (Flask + PostgreSQL + Pesapal IPN) in `backend/`
- **Frontend** → Vercel (static HTML/JS) in `frontend/`
- **Payments** → Pesapal (M-PESA, Airtel Money, T-Kash, Card)

## Deploy

### Render
1. New → **Blueprint** → select this repo → Render reads `backend/render.yaml`.
2. Set the `sync: false` secrets (see `backend/.env.example`).
3. After deploy, verify `/health`.
4. Register the Pesapal IPN once from a shell on Render:
   ```bash
   python -c "from services.payments import PaymentService; print(PaymentService().ensure_pesapal_ipn())"
## Cron Jobs

### Payment reminders (every 24h)
Add a **Render Cron Job** (or use an external scheduler like cron-job.org):

- **Command:** `curl -s "https://edupoint-api.onrender.com/api/cron/send-reminders?secret=$CRON_SECRET"`
- **Schedule:** `0 * * * *` (every hour — the endpoint itself only sends one reminder per 24h per invoice)
- **Env:** `CRON_SECRET` must match Render backend env var

This endpoint:
- Finds pending payments older than 24 hours
- Sends a reminder email with PAY NOW button (once per 24h per invoice)
- Updates `last_reminder_at` and `reminder_count` so it's tracked

### Pesapal IPN
The webhook URL `/api/payment/webhook/pesapal` is auto-registered on first payment.
Make sure `BACKEND_URL` is set so the IPN registers to your live domain, not `localhost`.
