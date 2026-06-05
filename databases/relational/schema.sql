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

    service_type           VARCHAR(30) NOT NULL, -- e.g. 'normal', 'express', 'metro'
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
--  FARE DATA
-- ============================================================

-- Ticket type master data, such as single, return, and day_pass.
CREATE TABLE IF NOT EXISTS ticket_types (
    ticket_type_id VARCHAR(20) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Defines which networks each ticket type can be used on.
-- M = metro, N = national rail.
CREATE TABLE IF NOT EXISTS ticket_type_networks (
    ticket_type_id VARCHAR(20) NOT NULL,
    network_id CHAR(1) NOT NULL,
    seat_assignment BOOLEAN NOT NULL DEFAULT FALSE,
    advance_purchase BOOLEAN NOT NULL DEFAULT FALSE,
    advance_purchase_max_days INTEGER,
    changes_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    change_fee_cents INTEGER,
    refundable BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    PRIMARY KEY (ticket_type_id, network_id),
    FOREIGN KEY (ticket_type_id) REFERENCES ticket_types (ticket_type_id) ON DELETE CASCADE,
    FOREIGN KEY (network_id) REFERENCES networks (network_id),
    CHECK (network_id IN ('M', 'N')),
    CHECK (
        advance_purchase_max_days IS NULL
        OR advance_purchase_max_days >= 0
    ),
    CHECK (
        change_fee_cents IS NULL
        OR change_fee_cents >= 0
    )
);

-- Fare or seat classes, such as general, standard, and first.
CREATE TABLE IF NOT EXISTS fare_classes (
    fare_class_id VARCHAR(20) PRIMARY KEY,
    network_id CHAR(1) NOT NULL,
    class_display_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (network_id) REFERENCES networks (network_id),
    UNIQUE (fare_class_id, network_id),
    CHECK (network_id IN ('M', 'N'))
);

-- Pricing rules. Monetary values are stored as USD cents, not floats. To avoid floating point precision issues.


CREATE TABLE IF NOT EXISTS fare_rules (
    fare_rule_id VARCHAR(30) PRIMARY KEY,

    network_id CHAR(1) NOT NULL,
    schedule_id VARCHAR(20),
    ticket_type_id VARCHAR(20) NOT NULL,
    fare_class_id VARCHAR(20),

-- Pricing model decides which fare amount columns must be filled.
-- stops_based: schedule fare without fare class, e.g. metro single.
-- stops_based_with_fare_class: schedule fare varies by class.
-- stops_based_per_leg: return ticket prices each leg separately.
-- flat_rate: fixed fare not tied to a schedule.
pricing_model VARCHAR(40) NOT NULL,

-- use "USD cents" to store monetary values, e.g. 250 means $2.50 USD
base_fare_cents INTEGER,
per_stop_rate_cents INTEGER,
flat_fare_cents INTEGER,
currency CHAR(3) NOT NULL DEFAULT 'USD',
effective_from DATE NOT NULL DEFAULT CURRENT_DATE, --Additional column to track when a fare rule becomes effective.
effective_to DATE, --Optional column to track when a fare rule is no longer effective. Null means it is currently active.
is_active BOOLEAN NOT NULL DEFAULT TRUE,
created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
FOREIGN KEY (network_id) REFERENCES networks (network_id),
FOREIGN KEY (schedule_id) REFERENCES schedule_services (schedule_id),
FOREIGN KEY (ticket_type_id) REFERENCES ticket_types (ticket_type_id),

-- Ensures the ticket type is actually available on this network.
FOREIGN KEY (ticket_type_id, network_id) REFERENCES ticket_type_networks (ticket_type_id, network_id),

-- Ensures the fare class belongs to the same network when present.
FOREIGN KEY (fare_class_id, network_id) REFERENCES fare_classes (fare_class_id, network_id),
CHECK (network_id IN ('M', 'N')),
CHECK (
    pricing_model IN (
        'stops_based',
        'stops_based_with_fare_class',
        'stops_based_per_leg',
        'flat_rate'
    )
),
CHECK (currency = 'USD'),
CHECK (
    base_fare_cents IS NULL
    OR base_fare_cents >= 0
),
CHECK (
    per_stop_rate_cents IS NULL
    OR per_stop_rate_cents >= 0
),
CHECK (
    flat_fare_cents IS NULL
    OR flat_fare_cents >= 0
),
CHECK (
    effective_to IS NULL
    OR effective_to >= effective_from
),
CHECK (
    -- flat_rate uses only flat_fare_cents, e.g. metro day pass.
    (
        pricing_model = 'flat_rate'
        AND schedule_id IS NULL
        AND fare_class_id IS NULL
        AND flat_fare_cents IS NOT NULL
        AND base_fare_cents IS NULL
        AND per_stop_rate_cents IS NULL
    )
    -- stops_based uses base + per-stop rate for one schedule.
    OR (
        pricing_model = 'stops_based'
        AND schedule_id IS NOT NULL
        AND fare_class_id IS NULL
        AND base_fare_cents IS NOT NULL
        AND per_stop_rate_cents IS NOT NULL
        AND flat_fare_cents IS NULL
    )
    -- Class-based models use base + per-stop rate for one schedule and class.
    OR (
        pricing_model IN (
            'stops_based_with_fare_class',
            'stops_based_per_leg'
        )
        AND schedule_id IS NOT NULL
        AND fare_class_id IS NOT NULL
        AND base_fare_cents IS NOT NULL
        AND per_stop_rate_cents IS NOT NULL
        AND flat_fare_cents IS NULL
    )
),

-- Ensures no duplicate fare rules for the same combination of network, schedule, ticket type, fare class, and effective date.
CONSTRAINT uq_fare_rules_unique
        UNIQUE NULLS NOT DISTINCT (
            network_id,
            schedule_id,
            ticket_type_id,
            fare_class_id,
            effective_from
        )
);

-- ============================================================
--  SEAT DATA
-- ============================================================

-- Seat layout assigned to a national rail schedule.
CREATE TABLE IF NOT EXISTS seat_layouts (
    layout_id VARCHAR(20) PRIMARY KEY,
    schedule_id VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (schedule_id) REFERENCES schedule_services (schedule_id),
    UNIQUE (schedule_id)
);

-- Coaches inside one seat layout, such as coach A or B.
CREATE TABLE IF NOT EXISTS coaches (
    coach_id VARCHAR(30) PRIMARY KEY, --seeded as layout_id + coach_code for simplicity
    layout_id VARCHAR(20) NOT NULL,
    coach_code VARCHAR(10) NOT NULL,
    fare_class_id VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (layout_id) REFERENCES seat_layouts (layout_id) ON DELETE CASCADE,
    FOREIGN KEY (fare_class_id) REFERENCES fare_classes (fare_class_id),
    UNIQUE (layout_id, coach_code)
);

-- Physical seats inside a coach. seat_code is only unique within a coach.


CREATE TABLE IF NOT EXISTS seats (
    seat_pk VARCHAR(40) PRIMARY KEY, --seeded as coach_id + seat_code for simplicity

    coach_id VARCHAR(30) NOT NULL,

    seat_code VARCHAR(10) NOT NULL, -- e.g. "1A", "2B". Not globally unique, only unique within a coach.
    seat_row INTEGER,
    seat_column VARCHAR(5),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (coach_id)
        REFERENCES coaches(coach_id)
        ON DELETE CASCADE,

    UNIQUE (coach_id, seat_code), -- Ensures no duplicate seat codes within the same coach.

CHECK ( seat_row IS NULL OR seat_row > 0 ) );

-- Seat reservations for a concrete departure and travel segment.


CREATE TABLE IF NOT EXISTS seat_reservations (
    seat_reservation_id VARCHAR(30) PRIMARY KEY,

    departure_id VARCHAR(30) NOT NULL,
    seat_pk VARCHAR(40) NOT NULL,
    booking_id VARCHAR(30) NOT NULL,

    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,

    origin_stop_sequence INTEGER NOT NULL,
    destination_stop_sequence INTEGER NOT NULL,

    reservation_status VARCHAR(20) NOT NULL,

    held_until TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (departure_id)
        REFERENCES service_departures(departure_id),

    FOREIGN KEY (seat_pk)
        REFERENCES seats(seat_pk),

-- Future FK after national_rail_booking is created:
-- FOREIGN KEY (booking_id)
--     REFERENCES national_rail_booking(booking_id),


FOREIGN KEY (origin_station_id)
        REFERENCES stations(station_id),

    FOREIGN KEY (destination_station_id)
        REFERENCES stations(station_id),

    CHECK (reservation_status IN (
        'held',
        'confirmed',
        'cancelled',
        'expired',
        'completed'
    )),
    CHECK (origin_stop_sequence < destination_stop_sequence)
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