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
-- Stores the primary contact information and lifecycle state for users.
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Serves as the surrogate primary key for underlying database relations.
    user_id VARCHAR(50) UNIQUE NOT NULL,            -- Acts as the business identifier for frontend display and external services (e.g., RU01).
    full_name VARCHAR(100) NOT NULL,                -- User's full legal name.
    email VARCHAR(255) UNIQUE NOT NULL,             -- Potential login identification.
    phone VARCHAR(50) NOT NULL,                     
    date_of_birth DATE NOT NULL,                    
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- Records the exact time the account was created.
    is_active BOOLEAN NOT NULL DEFAULT TRUE,          -- Indicates whether the account is active and permitted to access the system.
    deleted_at TIMESTAMPTZ                            -- Acts as a soft-deletion marker to maintain referential integrity.
);

-- Table: security_questions
-- Acts as a centralized lookup table for standardized security questions, ensuring data consistency and simplifying maintenance.
CREATE TABLE security_questions (
    id SERIAL PRIMARY KEY,                          -- Serves as the surrogate primary key for the lookup table.
    question_text VARCHAR(255) UNIQUE NOT NULL,     -- The actual text of the security question.
    is_active BOOLEAN NOT NULL DEFAULT TRUE           -- Indicates whether this question is currently available for new users to select during registration.
);

-- Table: user_credentials
-- Secures authentication keys, algorithms, and security questions. Restricted to Auth services.
CREATE TABLE user_credentials (
    user_profile_id UUID PRIMARY KEY,               -- Foreign key linking strictly one-to-one with user_profiles.
    password_hash VARCHAR(255) NOT NULL,            -- The securely hashed password string including its salt.
    hash_algorithm VARCHAR(20) DEFAULT 'Argon2id',  -- Identifies the algorithm used for the hash to allow future smooth migrations.
    security_question_id INT NOT NULL,              -- Foreign key referencing the standard security_questions lookup table.
    secret_answer_hash VARCHAR(255) NOT NULL,       -- The securely hashed answer to the security question.
    password_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- Tracks the last time the password was changed.
    
    -- Link to the user_profiles table: delete associated credentials when a user is deleted
    CONSTRAINT fk_user_profile
        FOREIGN KEY (user_profile_id) 
        REFERENCES user_profiles(id)
        ON DELETE CASCADE,
        
    -- Link to the security_questions table: set to RESTRICT to prevent administrators from accidentally deleting security questions that are still in use by users
    CONSTRAINT fk_security_question
        FOREIGN KEY (security_question_id)
        REFERENCES security_questions(id)
        ON DELETE RESTRICT
);

-- Create the Native ENUM type for login status
-- Defines a strict set of allowed values for login outcomes to ensure data integrity at the database level.
CREATE TYPE login_status_enum AS ENUM ('SUCCESS', 'FAILED');

-- Table: login_logs
-- Records an append-only audit trail of user login attempts.
CREATE TABLE login_logs (
    id BIGSERIAL PRIMARY KEY,                       -- Sequential primary key optimized for high-speed insert operations.
    user_profile_id UUID NOT NULL,                  -- Foreign key linking the log to a specific user profile.
    login_at TIMESTAMP NOT NULL,                    -- The exact time the login attempt occurred.
    status login_status_enum NOT NULL,              -- Indicates the outcome of the login attempt using a strict native ENUM.

    CONSTRAINT fk_login_logs_user
        FOREIGN KEY (user_profile_id) 
        REFERENCES user_profiles(id)
        ON DELETE CASCADE
);

-- Optimizes read performance for querying a specific user's most recent logins.
CREATE INDEX idx_login_logs_user_time ON login_logs(user_profile_id, login_at DESC);


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
