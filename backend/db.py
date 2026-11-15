import os
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def connect():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with connect() as conn:
        # --- USERS ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT, email TEXT UNIQUE, phone TEXT,
                password_hash TEXT, referral_code TEXT,
                role TEXT DEFAULT 'student', active INT DEFAULT 1,
                credits INT DEFAULT 0, created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        # Safely add missing columns to existing 'users' table
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS active INT DEFAULT 1;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'student';")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INT DEFAULT 0;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;")

        # --- PAYMENTS ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                transaction_id TEXT UNIQUE, user_id INT, phone TEXT,
                network TEXT, amount NUMERIC, plan TEXT, status TEXT,
                provider_reference TEXT, message TEXT, redirect_url TEXT,
                calculation_data JSONB, invoice_sent_at TIMESTAMPTZ,
                last_reminder_at TIMESTAMPTZ, reminder_count INT DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_sent_at TIMESTAMPTZ;")
        conn.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS last_reminder_at TIMESTAMPTZ;")
        conn.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS reminder_count INT DEFAULT 0;")
        
        # --- CALCULATIONS ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calculation_history (
                id SERIAL PRIMARY KEY, user_id INT, reference TEXT UNIQUE,
                cluster_points NUMERIC, created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("ALTER TABLE calculation_history ADD COLUMN IF NOT EXISTS report_status TEXT DEFAULT 'pending';")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calculation_subjects (
                id SERIAL PRIMARY KEY, history_id INT, subject TEXT, grade TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calculation_courses (
                id SERIAL PRIMARY KEY, history_id INT, course_name TEXT,
                university TEXT, cutoff NUMERIC, difference NUMERIC, match_type TEXT
            );
        """)
        
        # --- SESSIONS ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY, user_id INT, token TEXT UNIQUE,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)

        # --- ADMIN DASHBOARD TABLES ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_logs (
                id SERIAL PRIMARY KEY, user_id INT, email_to TEXT NOT NULL,
                email_type TEXT NOT NULL, subject TEXT, status TEXT DEFAULT 'queued',
                provider_message_id TEXT, error_message TEXT, attempts INT DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoice_records (
                id SERIAL PRIMARY KEY, invoice_number TEXT UNIQUE NOT NULL,
                transaction_id TEXT, user_id INT, amount NUMERIC(12,2),
                delivery_status TEXT DEFAULT 'generated', email_sent_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_versions (
                id SERIAL PRIMARY KEY, history_id INT NOT NULL, version INT DEFAULT 1,
                pdf_status TEXT DEFAULT 'generated', email_status TEXT DEFAULT 'pending',
                retry_count INT DEFAULT 0, created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_excel_reports (
                id SERIAL PRIMARY KEY, report_date DATE UNIQUE NOT NULL,
                filename TEXT NOT NULL, file_path TEXT, file_size INT,
                generated_at TIMESTAMPTZ DEFAULT now(), emailed_at TIMESTAMPTZ,
                status TEXT DEFAULT 'generated'
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_reminders (
                id SERIAL PRIMARY KEY, transaction_id TEXT NOT NULL,
                sent_at TIMESTAMPTZ DEFAULT now(), status TEXT DEFAULT 'sent'
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS platform_settings (
                key TEXT PRIMARY KEY, value JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT now(), updated_by INT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY, actor_id INT, actor_email TEXT,
                action TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
                details JSONB, ip_address TEXT, created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
