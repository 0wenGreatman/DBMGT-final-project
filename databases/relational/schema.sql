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

-- Ensure UUID generation functions are available in older PostgreSQL versions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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
    login_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),      -- The exact time the login attempt occurred.
    status login_status_enum NOT NULL,              -- Indicates the outcome of the login attempt using a strict native ENUM.

    CONSTRAINT fk_login_logs_user
        FOREIGN KEY (user_profile_id) 
        REFERENCES user_profiles(id)
        ON DELETE CASCADE
);

-- Optimizes read performance for querying a specific user's most recent logins.
CREATE INDEX idx_login_logs_user_time ON login_logs(user_profile_id, login_at DESC);


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
    FOREIGN KEY (schedule_id, line_id)
        REFERENCES schedule_services(schedule_id, line_id)
        ON DELETE CASCADE,

    FOREIGN KEY (station_id)
        REFERENCES stations(station_id),

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
    change_fee_usd DECIMAL(10, 2),
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
        change_fee_usd IS NULL
        OR change_fee_usd >= 0
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

-- Pricing rules. Monetary values use DECIMAL USD values, not FLOAT.
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

    -- Use DECIMAL for currency values to avoid floating point issues.
    -- All prices are in USD for simplicity.
    base_fare_usd DECIMAL(10, 2),
    per_stop_rate_usd DECIMAL(10, 2),
    price_usd DECIMAL(10, 2),

    currency CHAR(3) NOT NULL DEFAULT 'USD',
    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (network_id)
        REFERENCES networks(network_id),

    FOREIGN KEY (schedule_id)
        REFERENCES schedule_services(schedule_id),

    FOREIGN KEY (ticket_type_id)
        REFERENCES ticket_types(ticket_type_id),

    -- Ensures the ticket type is actually available on this network.
    FOREIGN KEY (ticket_type_id, network_id)
        REFERENCES ticket_type_networks(ticket_type_id, network_id),

    -- Ensures the fare class belongs to the same network when present.
    FOREIGN KEY (fare_class_id, network_id)
        REFERENCES fare_classes(fare_class_id, network_id),

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
        base_fare_usd IS NULL
        OR base_fare_usd >= 0
    ),
    CHECK (
        per_stop_rate_usd IS NULL
        OR per_stop_rate_usd >= 0
    ),
    CHECK (
        price_usd IS NULL
        OR price_usd >= 0
    ),
    CHECK (
        effective_to IS NULL
        OR effective_to >= effective_from
    ),
    CHECK (
        -- flat_rate uses only price_usd, e.g. metro day pass.
        (
            pricing_model = 'flat_rate'
            AND schedule_id IS NULL
            AND fare_class_id IS NULL
            AND price_usd IS NOT NULL
            AND base_fare_usd IS NULL
            AND per_stop_rate_usd IS NULL
        )
        -- stops_based uses base + per-stop rate for one schedule.
        OR (
            pricing_model = 'stops_based'
            AND schedule_id IS NOT NULL
            AND fare_class_id IS NULL
            AND base_fare_usd IS NOT NULL
            AND per_stop_rate_usd IS NOT NULL
            AND price_usd IS NULL
        )
        -- Class-based models use base + per-stop rate for one schedule and class.
        OR (
            pricing_model IN (
                'stops_based_with_fare_class',
                'stops_based_per_leg'
            )
            AND schedule_id IS NOT NULL
            AND fare_class_id IS NOT NULL
            AND base_fare_usd IS NOT NULL
            AND per_stop_rate_usd IS NOT NULL
            AND price_usd IS NULL
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
    -- Seeded as layout_id + coach_code for simplicity.
    coach_id VARCHAR(30) PRIMARY KEY,
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
    -- Seeded as coach_id + seat_code for simplicity.
    seat_pk VARCHAR(40) PRIMARY KEY,

    coach_id VARCHAR(30) NOT NULL,

    -- e.g. "1A", "2B"; not globally unique.
    seat_code VARCHAR(10) NOT NULL,
    seat_row INTEGER,
    seat_column VARCHAR(5),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (coach_id)
        REFERENCES coaches(coach_id)
        ON DELETE CASCADE,

    -- Ensures no duplicate seat codes within the same coach.
    UNIQUE (coach_id, seat_code),

    CHECK (
        seat_row IS NULL
        OR seat_row > 0
    )
);

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

-- ========================================
-- Booking / Travel History
-- ========================================

-- Bookings and travel history for National Rail. 
CREATE TABLE national_rail_booking (
    booking_id VARCHAR(20) PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    travel_date DATE NOT NULL,
    departure_id VARCHAR(20) NOT NULL,
    ticket_type_id VARCHAR(20) NOT NULL,
    amount_usd DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    booked_at TIMESTAMPTZ NOT NULL,
    travelled_at TIMESTAMPTZ,
    
    FOREIGN KEY (user_id)
        REFERENCES user_profiles(user_id),
    FOREIGN KEY (origin_station_id)
        REFERENCES stations(station_id),
    FOREIGN KEY (destination_station_id)
        REFERENCES stations(station_id),
    FOREIGN KEY (departure_id)
        REFERENCES service_departures(departure_id),
    FOREIGN KEY (ticket_type_id)
        REFERENCES ticket_types(ticket_type_id),
        
    CHECK (status IN ('confirmed', 'completed', 'cancelled')),
    CHECK (amount_usd > 0),
    CHECK (travel_date IS NOT NULL),
    CHECK (travelled_at IS NULL OR status = 'completed')
);

-- Bookings and travel history for Metro.
CREATE TABLE metro_booking (
    trip_id VARCHAR(20) PRIMARY KEY,  trip_id VARCHAR(20) PRIMARY KEY,  -- if this is the initial day pass purchase, it can be referenced by subsequent trips
    user_id VARCHAR(20) NOT NULL,
    schedule_id VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    travel_date DATE NOT NULL,
    ticket_type_id VARCHAR(20) NOT NULL,
    day_pass_ref VARCHAR(20),  -- Self-referencing FK to metro_booking(trip_id): links subsequent trips to their original day pass
    stops_travelled INTEGER,
    amount_usd DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    purchased_at TIMESTAMPTZ,
    travelled_at TIMESTAMPTZ,
    
    FOREIGN KEY (user_id)
        REFERENCES user_profiles(user_id),
    FOREIGN KEY (schedule_id)
        REFERENCES schedule_services(schedule_id),
    FOREIGN KEY (origin_station_id)
        REFERENCES stations(station_id),
    FOREIGN KEY (destination_station_id)
        REFERENCES stations(station_id),
    FOREIGN KEY (ticket_type_id)
        REFERENCES ticket_types(ticket_type_id),
    FOREIGN KEY (day_pass_ref)
        REFERENCES metro_booking(trip_id),
        
    CHECK (status IN ('completed', 'cancelled')),
    CHECK (amount_usd >= 0),
    CHECK (travel_date IS NOT NULL),
    CHECK (travelled_at IS NULL OR status = 'completed'),
    CHECK (stops_travelled IS NULL OR stops_travelled > 0),
    CHECK (day_pass_ref IS NULL OR amount_usd = 0)
);


-- ========================================
-- Payments
-- ========================================

-- Payment records for both National Rail and Metro.
CREATE TABLE payment_record (
    payment_id VARCHAR(20) PRIMARY KEY,
    amount_usd DECIMAL(10, 2) NOT NULL,
    method VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    paid_at TIMESTAMPTZ NOT NULL,
    
    CHECK (status IN ('paid', 'refunded')),
    CHECK (amount_usd > 0),
    CHECK (method IN ('credit_card', 'debit_card', 'ewallet'))
);

-- Linking payments to the bookings/trips for National Rail.
CREATE TABLE national_rail_payment_record (
    payment_id VARCHAR(20) PRIMARY KEY,
    booking_id VARCHAR(20) NOT NULL,
    
    FOREIGN KEY (payment_id)
        REFERENCES payment_record(payment_id),
    FOREIGN KEY (booking_id)
        REFERENCES national_rail_booking(booking_id)
);

-- Linking payments to the bookings/trips for Metro. Note that for Metro, multiple trips (day pass + subsequent trips) can reference the same payment record if they are linked by the day_pass_ref.
CREATE TABLE metro_payment_record (
    payment_id VARCHAR(20) PRIMARY KEY,
    trip_id VARCHAR(20) NOT NULL,
    
    FOREIGN KEY (payment_id)
        REFERENCES payment_record(payment_id),
    FOREIGN KEY (trip_id)
        REFERENCES metro_booking(trip_id)
);


-- ========================================
-- Feedback
-- ========================================

-- Feedback records for both National Rail and Metro.
CREATE TABLE feedback_base (
    feedback_id VARCHAR(20) PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    
    FOREIGN KEY (user_id)
        REFERENCES user_profiles(user_id),
        
    CHECK (rating >= 1 AND rating <= 5),
    CHECK (comment IS NULL OR LENGTH(comment) > 0)
);

-- Linking feedback to the bookings/trips for National Rail.
CREATE TABLE national_rail_feedback (
    feedback_id VARCHAR(20) PRIMARY KEY,
    booking_id VARCHAR(20) NOT NULL,
    
    FOREIGN KEY (feedback_id)
        REFERENCES feedback_base(feedback_id),
    FOREIGN KEY (booking_id)
        REFERENCES national_rail_booking(booking_id)
);

-- Linking feedback to the bookings/trips for Metro.
CREATE TABLE metro_feedback (
    feedback_id VARCHAR(20) PRIMARY KEY,
    trip_id VARCHAR(20) NOT NULL,
    
    FOREIGN KEY (feedback_id)
        REFERENCES feedback_base(feedback_id),
    FOREIGN KEY (trip_id)
        REFERENCES metro_booking(trip_id)
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