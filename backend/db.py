import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    referral_code TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    active INTEGER NOT NULL DEFAULT 1,
    credits INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS access(
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    paid INTEGER NOT NULL DEFAULT 0,
    plan TEXT,
    transaction_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments(
    id SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE NOT NULL,
    user_id INTEGER,
    provider_reference TEXT,
    phone TEXT NOT NULL,
    network TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    redirect_url TEXT,
    calculation_data JSONB,
    invoice_sent_at TIMESTAMPTZ,
    last_reminder_at TIMESTAMPTZ,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payments_provider_ref ON payments(provider_reference);
CREATE INDEX IF NOT EXISTS payments_status_idx ON payments(status);
CREATE TABLE IF NOT EXISTS sessions(
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS calculation_history(
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    reference TEXT UNIQUE NOT NULL,
    cluster_points NUMERIC(6,3) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS calculation_subjects(
    id SERIAL PRIMARY KEY,
    history_id INTEGER REFERENCES calculation_history(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    grade TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculation_courses(
    id SERIAL PRIMARY KEY,
    history_id INTEGER REFERENCES calculation_history(id) ON DELETE CASCADE,
    course_name TEXT NOT NULL,
    university TEXT NOT NULL,
    cutoff NUMERIC(6,3),
    difference NUMERIC(6,3),
    match_type TEXT NOT NULL
);
"""

def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS edupoint;")
        cur.execute("SET search_path TO edupoint;")
    conn.commit()
    return conn

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            # Migrate existing tables — add new columns if missing
            for col, col_type in [
                ("calculation_data", "JSONB"),
                ("invoice_sent_at", "TIMESTAMPTZ"),
                ("last_reminder_at", "TIMESTAMPTZ"),
                ("reminder_count", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema='edupoint' AND table_name='payments' 
                                         AND column_name='{col}') THEN
                            ALTER TABLE edupoint.payments ADD COLUMN {col} {col_type};
                        END IF;
                    END $$;
                """)
