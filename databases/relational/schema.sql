-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
--
--  Start from the mock data in train-mock-data/:
--    metro_stations.json, national_rail_stations.json
--    metro_schedules.json, national_rail_schedules.json
--    national_rail_seat_layouts.json
--    registered_users.json
--    bookings.json, metro_travel_history.json
--    payments.json, feedback.json
--
--  Think about:
--    - What tables do you need?
--    - What columns and data types?
--    - Which fields are primary keys? Which are foreign keys?
--    - What constraints make sense?
--
--  Apply your schema with:
--    docker-compose down -v && docker-compose up -d
-- ============================================================

-- Table: user_profiles
-- Function: Stores the primary contact information and lifecycle state for users.
-- Input: User's personal details provided during registration.
-- Output: Structured user profile data, filtered to exclude soft-deleted records for AI and business queries.
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Serves as the surrogate primary key for underlying database relations.
    user_id VARCHAR(50) UNIQUE NOT NULL,            -- Acts as the business identifier for frontend display and external services (e.g., RU01).
    full_name VARCHAR(100) NOT NULL,                -- Stores the user's full legal name.
    email VARCHAR(255) UNIQUE NOT NULL,             -- Stores the email address used for contact and potential login identification.
    phone VARCHAR(50) NOT NULL,                     -- Stores the contact phone number.
    date_of_birth DATE NOT NULL,                    -- Records the user's date of birth for age verification.
    registered_at TIMESTAMP NOT NULL,               -- Records the exact time the account was created.
    is_active BOOLEAN DEFAULT TRUE,                 -- Indicates whether the account is active and permitted to access the system.
    deleted_at TIMESTAMP DEFAULT NULL               -- Acts as a soft-deletion marker to maintain referential integrity.
);


-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,  -- 'refund', 'booking', 'conduct'
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);
