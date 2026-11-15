-- ============================================================
-- EduPointAI Admin Dashboard Migration
-- Safe to run multiple times (all CREATE ... IF NOT EXISTS)
-- ============================================================

CREATE TABLE IF NOT EXISTS email_logs (
  id SERIAL PRIMARY KEY,
  user_id INT,
  email_to TEXT NOT NULL,
  email_type TEXT NOT NULL,
  subject TEXT,
  status TEXT DEFAULT 'queued',
  provider_message_id TEXT,
  error_message TEXT,
  attempts INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);
CREATE INDEX IF NOT EXISTS idx_email_logs_created ON email_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_email_logs_user ON email_logs(user_id);

CREATE TABLE IF NOT EXISTS audit_logs (
  id SERIAL PRIMARY KEY,
  actor_id INT,
  actor_email TEXT,
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  details JSONB,
  ip_address TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

CREATE TABLE IF NOT EXISTS invoice_records (
  id SERIAL PRIMARY KEY,
  invoice_number TEXT UNIQUE NOT NULL,
  transaction_id TEXT,
  user_id INT,
  amount NUMERIC(12,2),
  delivery_status TEXT DEFAULT 'generated',
  email_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invoice_tx ON invoice_records(transaction_id);

CREATE TABLE IF NOT EXISTS report_versions (
  id SERIAL PRIMARY KEY,
  history_id INT NOT NULL,
  version INT DEFAULT 1,
  pdf_status TEXT DEFAULT 'generated',
  email_status TEXT DEFAULT 'pending',
  retry_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_report_versions_history ON report_versions(history_id);

CREATE TABLE IF NOT EXISTS platform_settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  updated_by INT
);

CREATE TABLE IF NOT EXISTS daily_excel_reports (
  id SERIAL PRIMARY KEY,
  report_date DATE UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  file_path TEXT,
  file_size INT,
  generated_at TIMESTAMPTZ DEFAULT now(),
  emailed_at TIMESTAMPTZ,
  status TEXT DEFAULT 'generated'
);

CREATE TABLE IF NOT EXISTS payment_reminders (
  id SERIAL PRIMARY KEY,
  transaction_id TEXT NOT NULL,
  sent_at TIMESTAMPTZ DEFAULT now(),
  status TEXT DEFAULT 'sent'
);
CREATE INDEX IF NOT EXISTS idx_payment_reminders_tx ON payment_reminders(transaction_id);

-- Seed defaults (safe to re-run)
INSERT INTO platform_settings (key, value) VALUES
  ('excel_automation', '{"enabled": false, "activated_at": null, "recipient": "academichelpdesk1@gmail.com"}'),
  ('reminders', '{"enabled": true, "interval_hours": 24, "max_reminders": 5}'),
  ('platform', '{"name": "EduPoint AI", "price_kes": 100}')
ON CONFLICT (key) DO NOTHING;
