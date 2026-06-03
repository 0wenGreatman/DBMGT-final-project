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




-- ============================================================
--  STATION AND ROUTE DATA
-- ============================================================

-- Two supported transit networks:
-- M = metro, N = national rail.
CREATE TABLE IF NOT EXISTS networks (
    network_id           CHAR(1)      PRIMARY KEY,
    network_display_name VARCHAR(100) NOT NULL,

    CHECK (network_id IN ('M', 'N'))
);

-- One row per physical station in either network.
CREATE TABLE IF NOT EXISTS stations (
    station_id   VARCHAR(10)  PRIMARY KEY,
    network_id   CHAR(1)      NOT NULL REFERENCES networks(network_id),
    station_name VARCHAR(100) NOT NULL,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- One row per route/line, such as M1 or NR1.
CREATE TABLE IF NOT EXISTS lines (
    line_id    VARCHAR(10)  PRIMARY KEY,
    network_id CHAR(1)      NOT NULL REFERENCES networks(network_id),
    line_name  VARCHAR(100) NOT NULL,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE
);

-- Actual station-line memberships.
-- Do not derive this by joining stations and lines on network_id only.
CREATE TABLE IF NOT EXISTS station_lines (
    station_id VARCHAR(10) NOT NULL REFERENCES stations(station_id),
    line_id    VARCHAR(10) NOT NULL REFERENCES lines(line_id),

    PRIMARY KEY (station_id, line_id)
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
