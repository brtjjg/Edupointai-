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
