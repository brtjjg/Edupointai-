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
