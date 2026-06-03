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
    network_id CHAR(1) PRIMARY KEY,
    network_display_name VARCHAR(100) NOT NULL,
    CHECK (network_id IN ('M', 'N'))
);

-- One row per physical station in either network.
CREATE TABLE IF NOT EXISTS stations (
    station_id VARCHAR(10) PRIMARY KEY,
    network_id CHAR(1) NOT NULL REFERENCES networks (network_id),
    station_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- One row per route/line, such as M1 or NR1.
CREATE TABLE IF NOT EXISTS lines (
    line_id VARCHAR(10) PRIMARY KEY,
    network_id CHAR(1) NOT NULL REFERENCES networks (network_id),
    line_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Actual station-line memberships.
-- Do not derive this by joining stations and lines on network_id only.
CREATE TABLE IF NOT EXISTS station_lines (
    station_id VARCHAR(10) NOT NULL REFERENCES stations (station_id),
    line_id VARCHAR(10) NOT NULL REFERENCES lines (line_id),
    PRIMARY KEY (station_id, line_id)
);

-- ============================================================
--  SCHEDULE DATA
-- ============================================================

-- Timetable header for one service pattern on a line.


CREATE TABLE IF NOT EXISTS schedule_services (
    schedule_id            VARCHAR(20) PRIMARY KEY,
    line_id                VARCHAR(10) NOT NULL,

    service_type           VARCHAR(30) NOT NULL,
    direction              VARCHAR(30) NOT NULL,

    origin_station_id      VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,

    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    frequency_min          INTEGER     NOT NULL,

    is_active              BOOLEAN     NOT NULL DEFAULT TRUE,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (line_id)
        REFERENCES lines(line_id),

    FOREIGN KEY (origin_station_id)
        REFERENCES stations(station_id),

    FOREIGN KEY (destination_station_id)
        REFERENCES stations(station_id),

-- Origin and destination must be valid stations on this line.


FOREIGN KEY (origin_station_id, line_id)
        REFERENCES station_lines(station_id, line_id),

    FOREIGN KEY (destination_station_id, line_id)
        REFERENCES station_lines(station_id, line_id),

    UNIQUE (schedule_id, line_id),

    CHECK (service_type IN ('metro', 'normal', 'express')),
    CHECK (direction IN ('northbound', 'southbound', 'eastbound', 'westbound')),
    CHECK (frequency_min > 0),
    CHECK (first_train_time < last_train_time)
);

-- Ordered stop list for each timetable.
-- line_id is included so each stop can be checked against station_lines.


CREATE TABLE IF NOT EXISTS schedule_stops (
    schedule_id                 VARCHAR(20) NOT NULL,
    line_id                     VARCHAR(10) NOT NULL,
    station_id                  VARCHAR(10) NOT NULL,

    stop_sequence               INTEGER NOT NULL,
    travel_time_from_origin_min INTEGER,

    is_boarding_allowed         BOOLEAN NOT NULL DEFAULT TRUE,
    is_alighting_allowed        BOOLEAN NOT NULL DEFAULT TRUE,
    is_pass_through             BOOLEAN NOT NULL DEFAULT FALSE,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (schedule_id, stop_sequence),
    UNIQUE (schedule_id, station_id),

    FOREIGN KEY (schedule_id)
        REFERENCES schedule_services(schedule_id)
        ON DELETE CASCADE,

-- Keeps this stop tied to the same line as the schedule header.
FOREIGN KEY (schedule_id, line_id) REFERENCES schedule_services (schedule_id, line_id) ON DELETE CASCADE,
FOREIGN KEY (station_id) REFERENCES stations (station_id),

-- Prevents a schedule from stopping at a station outside its line.


FOREIGN KEY (station_id, line_id)
        REFERENCES station_lines(station_id, line_id),

    CHECK (stop_sequence > 0),
    CHECK (
        travel_time_from_origin_min IS NULL
        OR travel_time_from_origin_min >= 0
    )
);

-- Days of week on which a schedule operates.
CREATE TABLE IF NOT EXISTS schedule_operating_days (
    schedule_id VARCHAR(20) NOT NULL,
    day_of_week VARCHAR(10) NOT NULL,
    PRIMARY KEY (schedule_id, day_of_week),
    FOREIGN KEY (schedule_id) REFERENCES schedule_services (schedule_id) ON DELETE CASCADE,
    CHECK (
        day_of_week IN (
            'mon',
            'tue',
            'wed',
            'thu',
            'fri',
            'sat',
            'sun'
        )
    )
);

-- Concrete train departures generated from a schedule for a service date.
CREATE TABLE IF NOT EXISTS service_departures (
    departure_id VARCHAR(30) PRIMARY KEY,
    schedule_id VARCHAR(20) NOT NULL,
    service_date DATE NOT NULL,
    departure_time TIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (schedule_id) REFERENCES schedule_services (schedule_id),
    UNIQUE (
        schedule_id,
        service_date,
        departure_time
    ),
    CHECK (
        status IN (
            'scheduled',
            'delayed',
            'cancelled'
        )
    )
);

-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL, -- 'refund', 'booking', 'conduct'
    content TEXT NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding vector (768),
    source_file VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);