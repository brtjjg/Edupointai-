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
    status TEXT DEFAULT 'active', 
    requires_approval BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS offer_claims(
    id SERIAL PRIMARY KEY,
    offer_id INTEGER REFERENCES offers(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    reference TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'approved', 
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
    status TEXT DEFAULT 'Discovered', 
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, scholarship_name)
);
CREATE TABLE IF NOT EXISTS saved_courses(
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    course_name TEXT NOT NULL,
    university TEXT NOT NULL,
    cutoff NUMERIC(6,3),
    UNIQUE(user_id, course_name, university)
);
CREATE TABLE IF NOT EXISTS student_cvs(
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    education TEXT,
    skills TEXT,
    experience TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS quiz_results(
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
"""

def _configure_connection(conn):
    """Automatically sets the schema every time a connection is used from the pool."""
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS edupoint;")
        cur.execute("SET search_path TO edupoint;")
    conn.commit()

# Initialize the Connection Pool once globally
if DATABASE_URL:
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        configure=_configure_connection
    )
    pool.wait() # Wait for the pool to establish initial connections
else:
    pool = None

def connect():
    if not pool:
        raise RuntimeError("DATABASE_URL is not set or pool is not initialized.")
    # Returns a context manager. When the 'with' block ends, the connection is returned to the pool automatically.
    return pool.connection()

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
