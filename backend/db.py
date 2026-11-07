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
    credits INTEGER NOT NULL DEFAULT 1,
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
CREATE TABLE IF NOT EXISTS offers(
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    image_url TEXT,
    offer_type TEXT NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    max_claims INTEGER NOT NULL,
    eligibility TEXT,
    button_text TEXT DEFAULT 'Grab This Offer',
    terms TEXT,
    visibility TEXT DEFAULT 'all',
    status TEXT DEFAULT 'active', -- draft, active, paused
    requires_approval BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS offer_claims(
    id SERIAL PRIMARY KEY,
    offer_id INTEGER REFERENCES offers(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    reference TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'approved', -- pending, approved, rejected, redeemed
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(offer_id, user_id)
);
CREATE TABLE IF NOT EXISTS offer_redemptions(
    id SERIAL PRIMARY KEY,
    claim_id INTEGER REFERENCES offer_claims(id) ON DELETE CASCADE,
    redeemed_at TIMESTAMPTZ DEFAULT now(),
    notes TEXT
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
CREATE TABLE IF NOT EXISTS student_scholarships(
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scholarship_name TEXT NOT NULL,
    status TEXT DEFAULT 'Discovered', -- Discovered, Interested, Preparing, Applied, Awarded, Rejected
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, scholarship_name)
);
"""

def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    # Create an isolated schema for EduPoint and set it as the default
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS edupoint;")
        cur.execute("SET search_path TO edupoint;")
    conn.commit()
    return conn

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            # 1. Create tables if they don't exist
            cur.execute(SCHEMA)
            
            # 2. Migration: Add 'credits' column if it's missing from existing tables
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_schema='edupoint' AND table_name='users' AND column_name='credits') THEN
                        ALTER TABLE edupoint.users ADD COLUMN credits INTEGER NOT NULL DEFAULT 1;
                    END IF;
                END $$;
            """)
