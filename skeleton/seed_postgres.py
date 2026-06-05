"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values
from argon2 import PasswordHasher

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # Each item in `data` is a dict — inspect the JSON to see available fields.
    pass


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_users(cur):
    data = load("registered_users.json")
    
    # Process and insert security_questions
    questions = list({u["secret_question"] for u in data if "secret_question" in u})
    insert_many(cur, "security_questions", ["question_text"], [(q,) for q in questions])
    
    cur.execute("SELECT id, question_text FROM security_questions")
    q_map = {row[1]: row[0] for row in cur.fetchall()}
    
    # Process and insert user_profiles
    user_rows = [(
        u["user_id"],
        u["full_name"],
        u["email"],
        u["phone"],
        u["date_of_birth"],
        u["registered_at"],
        u.get("is_active", True)
    ) for u in data]
    
    insert_many(cur, "user_profiles", 
        ["user_id", "full_name", "email", "phone", "date_of_birth", "registered_at", "is_active"], 
        user_rows)
        
    # Get DB-generated UUIDs for subsequent associations
    cur.execute("SELECT id, user_id FROM user_profiles")
    u_map = {row[1]: row[0] for row in cur.fetchall()}
    
    # Process and insert user_credentials and login_logs
    ph = PasswordHasher()
    cred_rows = []
    log_rows = []
    for u in data:
        uid = u_map.get(u["user_id"])
        if not uid:
            continue
            
        cred_rows.append((
            uid,
            ph.hash(u["password"]),  # Use argon2 for password hash
            "Argon2id",
            q_map[u["secret_question"]],
            ph.hash(u["secret_answer"]),  # Use argon2 for secret_answer hash
            u["registered_at"]
        ))
        
        # Generate initial SUCCESS login log only for active users
        if u.get("is_active", True):
            log_rows.append((
                uid,
                u["registered_at"],
                "SUCCESS"
            ))
        
    insert_many(cur, "user_credentials",
        ["user_profile_id", "password_hash", "hash_algorithm", "security_question_id", "secret_answer_hash", "password_updated_at"],
        cred_rows)
        
    insert_many(cur, "login_logs",
        ["user_profile_id", "login_at", "status"],
        log_rows)


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_payments(cur):
    data = load("payments.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


def seed_feedback(cur):
    data = load("feedback.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    pass


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Seeding tables (dependency order):")
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        conn.commit()
        print("\nAll done. Database seeded successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
