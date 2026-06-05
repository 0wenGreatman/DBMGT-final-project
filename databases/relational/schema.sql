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
        REFERENCES user_profile(user_id),
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
        REFERENCES user_profile(user_id),
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
        REFERENCES user_profile(user_id),
        
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