import os
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payments_provider_ref ON payments(provider_reference);
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

def _configure_connection(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS edupoint;")
        cur.execute("SET search_path TO edupoint;")
    conn.commit()

if DATABASE_URL:
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        configure=_configure_connection
    )
    pool.wait()
else:
    pool = None

def connect():
    if not pool:
        raise RuntimeError("DATABASE_URL is not set or pool is not initialized.")
    return pool.connection()

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            # Safely add calculation_data if it doesn't exist
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_schema='edupoint' AND table_name='payments' AND column_name='calculation_data') THEN
                        ALTER TABLE edupoint.payments ADD COLUMN calculation_data JSONB;
                    END IF;
                END $$;
            """)
