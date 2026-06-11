"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _row_to_dict(row) -> dict:
    return {key: _jsonable(value) for key, value in dict(row).items()}


def _positive_int(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# TODO: Implement the query_ and execute_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        travel_date:     e.g. "2025-06-01" — used to count bookings; omit for general info
    """
    sql = """
        WITH candidates AS (
            SELECT
                ss.schedule_id,
                ss.line_id AS line,
                l.line_name,
                ss.service_type,
                ss.direction,
                ss.first_train_time,
                ss.last_train_time,
                ss.frequency_min,
                origin_stop.station_id AS origin_id,
                origin_station.station_name AS origin_name,
                destination_stop.station_id AS destination_id,
                destination_station.station_name AS destination_name,
                origin_stop.stop_sequence AS origin_stop_sequence,
                destination_stop.stop_sequence AS destination_stop_sequence,
                destination_stop.stop_sequence - origin_stop.stop_sequence AS stops_travelled,
                CASE
                    WHEN origin_stop.travel_time_from_origin_min IS NOT NULL
                     AND destination_stop.travel_time_from_origin_min IS NOT NULL
                    THEN destination_stop.travel_time_from_origin_min
                       - origin_stop.travel_time_from_origin_min
                    ELSE NULL
                END AS travel_time_min
            FROM schedule_services ss
            JOIN lines l
                ON l.line_id = ss.line_id
            JOIN schedule_stops origin_stop
                ON origin_stop.schedule_id = ss.schedule_id
               AND origin_stop.station_id = %s
            JOIN stations origin_station
                ON origin_station.station_id = origin_stop.station_id
            JOIN schedule_stops destination_stop
                ON destination_stop.schedule_id = ss.schedule_id
               AND destination_stop.station_id = %s
            JOIN stations destination_station
                ON destination_station.station_id = destination_stop.station_id
            WHERE ss.service_type IN ('normal', 'express')
              AND ss.is_active = TRUE
              AND l.network_id = 'N'
              AND l.is_active = TRUE
              AND origin_station.is_active = TRUE
              AND destination_station.is_active = TRUE
              AND origin_stop.is_boarding_allowed = TRUE
              AND destination_stop.is_alighting_allowed = TRUE
              AND origin_stop.stop_sequence < destination_stop.stop_sequence
              AND (
                    %s::date IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM schedule_operating_days sod
                        WHERE sod.schedule_id = ss.schedule_id
                          AND sod.day_of_week = lower(to_char(%s::date, 'Dy'))
                    )
              )
        )
        SELECT
            c.*,
            stop_list.stops_in_order,
            stop_list.station_names_in_order,
            COALESCE(fare_info.fare_classes, '[]'::json) AS fare_classes,
            departure_info.departure_id,
            COALESCE(departure_info.departure_time, c.first_train_time) AS departure_time,
            COALESCE(departure_info.departure_status, 'timetable') AS departure_status,
            COALESCE(seat_info.total_seats, 0) AS total_seats,
            COALESCE(seat_info.reserved_seats, 0) AS reserved_seats,
            COALESCE(seat_info.total_seats, 0)
                - COALESCE(seat_info.reserved_seats, 0) AS available_seats
        FROM candidates c
        LEFT JOIN LATERAL (
            SELECT
                array_agg(st.station_id ORDER BY st.stop_sequence) AS stops_in_order,
                array_agg(s.station_name ORDER BY st.stop_sequence) AS station_names_in_order
            FROM schedule_stops st
            JOIN stations s
                ON s.station_id = st.station_id
            WHERE st.schedule_id = c.schedule_id
        ) stop_list ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                json_agg(
                    json_build_object(
                        'fare_class', fr.fare_class_id,
                        'base_fare_usd', fr.base_fare_usd,
                        'per_stop_rate_usd', fr.per_stop_rate_usd,
                        'currency', fr.currency
                    )
                    ORDER BY fr.fare_class_id
                ) AS fare_classes
            FROM fare_rules fr
            WHERE fr.network_id = 'N'
              AND fr.schedule_id = c.schedule_id
              AND fr.ticket_type_id = 'single'
              AND fr.pricing_model = 'stops_based_with_fare_class'
              AND fr.is_active = TRUE
              AND CURRENT_DATE >= fr.effective_from
              AND (fr.effective_to IS NULL OR CURRENT_DATE <= fr.effective_to)
        ) fare_info ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                sd.departure_id,
                sd.departure_time,
                sd.status AS departure_status
            FROM service_departures sd
            WHERE %s::date IS NOT NULL
              AND sd.schedule_id = c.schedule_id
              AND sd.service_date = %s::date
              AND sd.status <> 'cancelled'
            ORDER BY sd.departure_time
            LIMIT 1
        ) departure_info ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                COUNT(s.seat_pk)::int AS total_seats,
                COUNT(DISTINCT sr.seat_pk)::int AS reserved_seats
            FROM seat_layouts sl
            JOIN coaches co
                ON co.seat_layout_pk = sl.seat_layout_pk
               AND co.is_active = TRUE
            JOIN seats s
                ON s.coach_pk = co.coach_pk
               AND s.is_active = TRUE
            LEFT JOIN seat_reservations sr
                ON sr.departure_id = departure_info.departure_id
               AND sr.seat_pk = s.seat_pk
               AND sr.reservation_status IN ('held', 'confirmed', 'completed')
               AND (
                    sr.reservation_status <> 'held'
                    OR sr.held_until IS NULL
                    OR sr.held_until > CURRENT_TIMESTAMP
               )
            WHERE sl.schedule_id = c.schedule_id
              AND sl.is_active = TRUE
        ) seat_info ON TRUE
        ORDER BY c.line, c.first_train_time, c.schedule_id;
    """
    params = (
        origin_id,
        destination_id,
        travel_date,
        travel_date,
        travel_date,
        travel_date,
    )
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_row_to_dict(row) for row in cur.fetchall()]


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """
    Calculate the fare for a national rail journey.

    Args:
        schedule_id:     e.g. "NR_SCH01"
        fare_class:      "standard" or "first"
        stops_travelled: number of stops between origin and destination (inclusive)

    Returns:
        dict with fare_class, base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    stops_travelled = _positive_int(stops_travelled)
    if stops_travelled is None:
        return None

    sql = """
        SELECT
            fare_rule_code AS fare_rule_id,
            fare_class_id AS fare_class,
            base_fare_usd,
            per_stop_rate_usd,
            currency
        FROM fare_rules
        WHERE network_id = 'N'
          AND schedule_id = %s
          AND ticket_type_id = 'single'
          AND fare_class_id = %s
          AND pricing_model = 'stops_based_with_fare_class'
          AND is_active = TRUE
          AND CURRENT_DATE >= effective_from
          AND (effective_to IS NULL OR CURRENT_DATE <= effective_to)
        ORDER BY effective_from DESC
        LIMIT 1;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, fare_class))
            row = cur.fetchone()

    if not row:
        return None

    result = dict(row)
    total = result["base_fare_usd"] + result["per_stop_rate_usd"] * stops_travelled
    result["stops_travelled"] = stops_travelled
    result["total_fare_usd"] = total
    return _row_to_dict(result)


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.

    Args:
        origin_id:       e.g. "MS01"
        destination_id:  e.g. "MS09"
    """
    sql = """
        WITH candidates AS (
            SELECT
                ss.schedule_id,
                ss.line_id AS line,
                l.line_name,
                ss.service_type,
                ss.direction,
                ss.first_train_time,
                ss.last_train_time,
                ss.frequency_min,
                origin_stop.station_id AS origin_id,
                origin_station.station_name AS origin_name,
                destination_stop.station_id AS destination_id,
                destination_station.station_name AS destination_name,
                origin_stop.stop_sequence AS origin_stop_sequence,
                destination_stop.stop_sequence AS destination_stop_sequence,
                destination_stop.stop_sequence - origin_stop.stop_sequence AS stops_travelled,
                CASE
                    WHEN origin_stop.travel_time_from_origin_min IS NOT NULL
                     AND destination_stop.travel_time_from_origin_min IS NOT NULL
                    THEN destination_stop.travel_time_from_origin_min
                       - origin_stop.travel_time_from_origin_min
                    ELSE NULL
                END AS travel_time_min
            FROM schedule_services ss
            JOIN lines l
                ON l.line_id = ss.line_id
            JOIN schedule_stops origin_stop
                ON origin_stop.schedule_id = ss.schedule_id
               AND origin_stop.station_id = %s
            JOIN stations origin_station
                ON origin_station.station_id = origin_stop.station_id
            JOIN schedule_stops destination_stop
                ON destination_stop.schedule_id = ss.schedule_id
               AND destination_stop.station_id = %s
            JOIN stations destination_station
                ON destination_station.station_id = destination_stop.station_id
            WHERE ss.service_type = 'metro'
              AND ss.is_active = TRUE
              AND l.network_id = 'M'
              AND l.is_active = TRUE
              AND origin_station.is_active = TRUE
              AND destination_station.is_active = TRUE
              AND origin_stop.is_boarding_allowed = TRUE
              AND destination_stop.is_alighting_allowed = TRUE
              AND origin_stop.stop_sequence < destination_stop.stop_sequence
        )
        SELECT
            c.*,
            stop_list.stops_in_order,
            stop_list.station_names_in_order,
            COALESCE(operating_days.operates_on, ARRAY[]::varchar[]) AS operates_on
        FROM candidates c
        LEFT JOIN LATERAL (
            SELECT
                array_agg(st.station_id ORDER BY st.stop_sequence) AS stops_in_order,
                array_agg(s.station_name ORDER BY st.stop_sequence) AS station_names_in_order
            FROM schedule_stops st
            JOIN stations s
                ON s.station_id = st.station_id
            WHERE st.schedule_id = c.schedule_id
        ) stop_list ON TRUE
        LEFT JOIN LATERAL (
            SELECT array_agg(
                sod.day_of_week
                ORDER BY CASE sod.day_of_week
                    WHEN 'mon' THEN 1
                    WHEN 'tue' THEN 2
                    WHEN 'wed' THEN 3
                    WHEN 'thu' THEN 4
                    WHEN 'fri' THEN 5
                    WHEN 'sat' THEN 6
                    WHEN 'sun' THEN 7
                END
            ) AS operates_on
            FROM schedule_operating_days sod
            WHERE sod.schedule_id = c.schedule_id
        ) operating_days ON TRUE
        ORDER BY c.line, c.first_train_time, c.schedule_id;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [_row_to_dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.

    Args:
        schedule_id:     e.g. "MS_SCH01"
        stops_travelled: number of stops between origin and destination

    Returns:
        dict with base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    stops_travelled = _positive_int(stops_travelled)
    if stops_travelled is None:
        return None

    sql = """
        SELECT
            fare_rule_code AS fare_rule_id,
            base_fare_usd,
            per_stop_rate_usd,
            currency
        FROM fare_rules
        WHERE network_id = 'M'
          AND schedule_id = %s
          AND ticket_type_id = 'single'
          AND fare_class_id IS NULL
          AND pricing_model = 'stops_based'
          AND is_active = TRUE
          AND CURRENT_DATE >= effective_from
          AND (effective_to IS NULL OR CURRENT_DATE <= effective_to)
        ORDER BY effective_from DESC
        LIMIT 1;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()

    if not row:
        return None

    result = dict(row)
    total = result["base_fare_usd"] + result["per_stop_rate_usd"] * stops_travelled
    result["stops_travelled"] = stops_travelled
    result["total_fare_usd"] = total
    return _row_to_dict(result)


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.

    Args:
        schedule_id:  e.g. "NR_SCH01"
        travel_date:  e.g. "2025-06-01"
        fare_class:   "standard" or "first"

    Returns:
        List of dicts: {seat_id, coach, row, column}
    """
    sql = """
        SELECT
            s.seat_code AS seat_id,
            c.coach_code AS coach,
            s.seat_row AS row,
            s.seat_column AS column,
            c.fare_class_id AS fare_class,
            cd.departure_id,
            cd.departure_time
        FROM seat_layouts sl
        LEFT JOIN LATERAL (
            SELECT
                departure_id,
                departure_time
            FROM service_departures
            WHERE schedule_id = sl.schedule_id
              AND service_date = %s::date
              AND status <> 'cancelled'
            ORDER BY departure_time
            LIMIT 1
        ) cd ON TRUE
        JOIN coaches c
            ON c.seat_layout_pk = sl.seat_layout_pk
           AND c.fare_class_id = %s
           AND c.is_active = TRUE
        JOIN seats s
            ON s.coach_pk = c.coach_pk
           AND s.is_active = TRUE
        LEFT JOIN seat_reservations sr
            ON sr.departure_id = cd.departure_id
           AND sr.seat_pk = s.seat_pk
           AND sr.reservation_status IN ('held', 'confirmed', 'completed')
           AND (
                sr.reservation_status <> 'held'
                OR sr.held_until IS NULL
                OR sr.held_until > CURRENT_TIMESTAMP
           )
        WHERE sr.seat_reservation_pk IS NULL
          AND sl.schedule_id = %s
          AND sl.is_active = TRUE
        ORDER BY c.coach_code, s.seat_row, s.seat_column, s.seat_code;
    """
    params = (travel_date, fare_class, schedule_id)
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_row_to_dict(row) for row in cur.fetchall()]


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.

    Args:
        available_seats: output of query_available_seats()
        count:           number of seats needed
    """
    if not available_seats or count <= 0:
        return []

    from collections import defaultdict

    def column_rank(column) -> int:
        text = str(column or "").strip().upper()
        if text.isalpha():
            rank = 0
            for char in text:
                rank = rank * 26 + ord(char) - ord("A") + 1
            return rank
        if text.isdigit():
            return int(text)
        return 10_000

    def seat_sort_key(seat: dict):
        row = seat.get("row")
        row_key = row if isinstance(row, int) else 10_000
        return (
            seat.get("coach") or "",
            row_key,
            column_rank(seat.get("column")),
            seat.get("seat_id") or "",
        )

    seats = sorted(
        [seat for seat in available_seats if seat.get("seat_id")],
        key=seat_sort_key,
    )
    if count >= len(seats):
        return [seat["seat_id"] for seat in seats[:count]]

    coaches: dict[str, list[dict]] = defaultdict(list)
    for seat in seats:
        coaches[seat.get("coach") or ""].append(seat)

    for coach_seats in coaches.values():
        rows: dict[int, list[dict]] = defaultdict(list)
        for seat in coach_seats:
            row = seat.get("row")
            if isinstance(row, int):
                rows[row].append(seat)

        for row_seats in sorted(rows.values(), key=lambda row: row[0]["row"]):
            row_seats = sorted(row_seats, key=seat_sort_key)
            if len(row_seats) < count:
                continue

            ranks = [column_rank(seat.get("column")) for seat in row_seats]
            for start in range(0, len(row_seats) - count + 1):
                window = row_seats[start:start + count]
                window_ranks = ranks[start:start + count]
                if all(
                    window_ranks[i + 1] == window_ranks[i] + 1
                    for i in range(len(window_ranks) - 1)
                ):
                    return [seat["seat_id"] for seat in window]

            return [seat["seat_id"] for seat in row_seats[:count]]

    for coach_seats in coaches.values():
        if len(coach_seats) >= count:
            best_window = min(
                (
                    coach_seats[start:start + count]
                    for start in range(0, len(coach_seats) - count + 1)
                ),
                key=lambda window: (
                    max(seat.get("row") or 10_000 for seat in window)
                    - min(seat.get("row") or 10_000 for seat in window),
                    seat_sort_key(window[0]),
                ),
            )
            return [seat["seat_id"] for seat in best_window]

    return [seat["seat_id"] for seat in seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    raise NotImplementedError("TODO: implement after designing your schema")


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).

    Returns:
        dict with keys 'national_rail' (list) and 'metro' (list)
    """
    sql_nr = """
        SELECT
            nb.booking_id,
            up.user_id,
            ss.schedule_id,
            ss.line_id,
            ss.service_type,
            ss.direction,
            origin.station_id AS origin_station_id,
            origin.station_name AS origin_station_name,
            destination.station_id AS destination_station_id,
            destination.station_name AS destination_station_name,
            nb.travel_date,
            sd.departure_id,
            sd.departure_time,
            tt.ticket_type_id AS ticket_type,
            nb.amount_usd,
            nb.status,
            nb.booked_at,
            nb.travelled_at
        FROM national_rail_booking nb
        JOIN user_profiles up
            ON up.id = nb.user_profile_id
        JOIN stations origin
            ON origin.station_pk = nb.origin_station_pk
        JOIN stations destination
            ON destination.station_pk = nb.destination_station_pk
        JOIN service_departures sd
            ON sd.service_departure_pk = nb.service_departure_pk
        JOIN schedule_services ss
            ON ss.schedule_id = sd.schedule_id
        JOIN ticket_types tt
            ON tt.ticket_type_pk = nb.ticket_type_pk
        WHERE up.email = %s
        ORDER BY nb.travel_date DESC, nb.booked_at DESC;
    """

    sql_metro = """
        SELECT
            mb.trip_id,
            up.user_id,
            ss.schedule_id,
            ss.line_id,
            ss.service_type,
            ss.direction,
            origin.station_id AS origin_station_id,
            origin.station_name AS origin_station_name,
            destination.station_id AS destination_station_id,
            destination.station_name AS destination_station_name,
            mb.travel_date,
            tt.ticket_type_id AS ticket_type,
            mb.day_pass_ref,
            mb.stops_travelled,
            mb.amount_usd,
            mb.status,
            mb.purchased_at,
            mb.travelled_at
        FROM metro_booking mb
        JOIN user_profiles up
            ON up.id = mb.user_profile_id
        JOIN schedule_services ss
            ON ss.schedule_service_pk = mb.schedule_service_pk
        JOIN stations origin
            ON origin.station_pk = mb.origin_station_pk
        JOIN stations destination
            ON destination.station_pk = mb.destination_station_pk
        JOIN ticket_types tt
            ON tt.ticket_type_pk = mb.ticket_type_pk
        WHERE up.email = %s
        ORDER BY mb.travel_date DESC, mb.purchased_at DESC;
    """

    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_nr, (user_email,))
            national_rail = [_row_to_dict(row) for row in cur.fetchall()]

            cur.execute(sql_metro, (user_email,))
            metro = [_row_to_dict(row) for row in cur.fetchall()]

    return {
        "national_rail": national_rail,
        "metro": metro,
    }


def query_payment_info(booking_id: str) -> Optional[dict]:
    """
    Return payment record for a booking or metro trip.
    
    Args:
        booking_id: e.g. "BK001" (national rail) or "MT001" (metro)
    
    Returns:
        dict with payment_id, amount_usd, method, status, paid_at
        or None if not found
    """
    if not booking_id:
        return None
    
    # Determine booking type by prefix: "BK" for national rail, "MT" for metro
    is_national_rail = booking_id.upper().startswith("BK")
    is_metro = booking_id.upper().startswith("MT")
    
    if is_national_rail:
        sql = """
            SELECT
                pr.payment_id,
                pr.amount_usd,
                pr.method,
                pr.status,
                pr.paid_at
            FROM payment_record pr
            JOIN national_rail_payment_record nrpr
                ON nrpr.payment_pk = pr.payment_pk
            JOIN national_rail_booking nrb
                ON nrb.booking_pk = nrpr.booking_pk
            WHERE nrb.booking_id = %s
            ORDER BY pr.paid_at DESC, pr.payment_pk DESC
            LIMIT 1
        """
    elif is_metro:
        sql = """
            SELECT
                pr.payment_id,
                pr.amount_usd,
                pr.method,
                pr.status,
                pr.paid_at
            FROM payment_record pr
            JOIN metro_payment_record mrpr
                ON mrpr.payment_pk = pr.payment_pk
            JOIN metro_booking mb
                ON mb.trip_pk = mrpr.trip_pk
            WHERE mb.trip_id = %s
            ORDER BY pr.paid_at DESC, pr.payment_pk DESC
            LIMIT 1
        """
    else:
        return None
    
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
            row = cur.fetchone()
    
    if not row:
        return None
    
    return _row_to_dict(row)


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.

    Args:
        user_id:                e.g. "RU01" — must match the logged-in user
        schedule_id:            e.g. "NR_SCH01"
        origin_station_id:      e.g. "NR01"
        destination_station_id: e.g. "NR05"
        travel_date:            e.g. "2025-06-01"
        fare_class:             "standard" or "first"
        seat_id:                e.g. "B05" (or "any" to auto-assign)
        ticket_type:            "single" (default) or "return"

    Returns:
        (True, booking_dict)   on success
        (False, error_message) on failure
    """
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Verify user exists and is active
        cur.execute(
            "SELECT id FROM user_profiles WHERE user_id = %s AND is_active = TRUE",
            (user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return False, "User not found or inactive"
        user_profile_id = user_row["id"]

        # Verify schedule exists and is active
        cur.execute("""
            SELECT ss.schedule_id
            FROM schedule_services ss
            WHERE ss.schedule_id = %s
              AND ss.is_active = TRUE
              AND ss.service_type IN ('normal', 'express')
        """, (schedule_id,))
        if not cur.fetchone():
            return False, "Schedule not found or inactive"

        # Validate origin station: exists, allows boarding, is part of schedule
        cur.execute("""
            SELECT st.stop_sequence, s.station_pk
            FROM schedule_stops st
            JOIN stations s ON s.station_id = st.station_id
            WHERE st.schedule_id = %s
              AND st.station_id = %s
              AND st.is_boarding_allowed = TRUE
        """, (schedule_id, origin_station_id))
        origin_row = cur.fetchone()
        if not origin_row:
            return False, "Origin station not valid or boarding not allowed"
        origin_seq = origin_row['stop_sequence']
        origin_station_pk = origin_row['station_pk']

        # Validate destination station: exists, allows alighting, is part of schedule
        cur.execute("""
            SELECT st.stop_sequence, s.station_pk
            FROM schedule_stops st
            JOIN stations s ON s.station_id = st.station_id
            WHERE st.schedule_id = %s
              AND st.station_id = %s
              AND st.is_alighting_allowed = TRUE
        """, (schedule_id, destination_station_id))
        dest_row = cur.fetchone()
        if not dest_row:
            return False, "Destination station not valid or alighting not allowed"
        dest_seq = dest_row['stop_sequence']
        destination_station_pk = dest_row['station_pk']

        # Verify origin comes before destination in the route
        if origin_seq >= dest_seq:
            return False, "Origin must come before destination"

        stops_travelled = dest_seq - origin_seq

        # Query departure for the requested travel date
        cur.execute("""
            SELECT service_departure_pk, departure_id, departure_time
            FROM service_departures
            WHERE schedule_id = %s
              AND service_date = %s::date
              AND status <> 'cancelled'
            ORDER BY departure_time
            LIMIT 1
        """, (schedule_id, travel_date))
        departure_row = cur.fetchone()
        if not departure_row:
            return False, "No available departure for this date"
        departure_id = departure_row['departure_id']
        service_departure_pk = departure_row['service_departure_pk']

        # Verify ticket type exists in the system
        cur.execute("""
            SELECT tt.ticket_type_pk
            FROM ticket_types tt
            JOIN ticket_type_networks ttn
                ON ttn.ticket_type_id = tt.ticket_type_id
               AND ttn.network_id = 'N'
            WHERE tt.ticket_type_id = %s
              AND tt.is_active = TRUE
        """, (ticket_type,))
        ticket_type_row = cur.fetchone()
        if not ticket_type_row:
            return False, f"Ticket type '{ticket_type}' not found"
        ticket_type_pk = ticket_type_row['ticket_type_pk']

        # Calculate fare based on schedule, fare class, and distance (stops travelled)
        fare_info = query_national_rail_fare(schedule_id, fare_class, stops_travelled)
        if not fare_info:
            return False, f"No fare rule for {fare_class} class on this schedule"
        amount_usd = Decimal(str(fare_info['total_fare_usd']))

        # Handle seat assignment: auto-select or validate user-provided seat
        if seat_id.lower() == "any":
            # Auto-select seats that are adjacent when possible
            available_seats = query_available_seats(schedule_id, travel_date, fare_class)
            if not available_seats:
                return False, "No available seats for this journey"
            selected = auto_select_adjacent_seats(available_seats, 1)
            if not selected:
                return False, "Unable to auto-select a seat"
            seat_id = selected[0]

        # Verify seat is valid for the selected fare class and schedule
        cur.execute("""
            SELECT s.seat_pk FROM seats s
            JOIN coaches c ON c.coach_pk = s.coach_pk
            JOIN seat_layouts sl ON sl.seat_layout_pk = c.seat_layout_pk
            WHERE sl.schedule_id = %s
              AND s.seat_code = %s
              AND c.fare_class_id = %s
              AND s.is_active = TRUE
              AND c.is_active = TRUE
            FOR UPDATE OF s
        """, (schedule_id, seat_id, fare_class))
        seat_row = cur.fetchone()
        if not seat_row:
            return False, f"Seat {seat_id} invalid for {fare_class} class"
        seat_pk = seat_row['seat_pk']

        # Check if seat is already reserved on this departure
        cur.execute("""
            SELECT seat_reservation_pk FROM seat_reservations
            WHERE departure_id = %s
              AND seat_pk = %s
              AND reservation_status IN ('held', 'confirmed', 'completed')
              AND (reservation_status <> 'held' 
                   OR held_until IS NULL 
                   OR held_until > CURRENT_TIMESTAMP)
        """, (departure_id, seat_pk))
        if cur.fetchone():
            return False, f"Seat {seat_id} is already reserved"

        # Create the booking record
        booking_id = _gen_booking_id()
        now = datetime.now(timezone.utc)

        cur.execute("""
            INSERT INTO national_rail_booking (
                booking_id, user_profile_id, origin_station_pk, destination_station_pk,
                travel_date, service_departure_pk, ticket_type_pk, amount_usd,
                status, booked_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING booking_pk, booking_id, user_profile_id, travel_date,
                      amount_usd, status, booked_at
        """, (
            booking_id, user_profile_id, origin_station_pk, destination_station_pk,
            travel_date, service_departure_pk, ticket_type_pk, amount_usd,
            'confirmed', now
        ))

        booking = cur.fetchone()
        if not booking:
            conn.rollback()
            return False, "Failed to create booking record"

        # Create seat reservation with confirmed status
        cur.execute("""
            INSERT INTO seat_reservations (
                departure_id, seat_pk, booking_id, origin_station_id,
                destination_station_id, origin_stop_sequence, destination_stop_sequence,
                reservation_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            departure_id, seat_pk, booking_id, origin_station_id,
            destination_station_id, origin_seq, dest_seq, 'confirmed'
        ))

        # The rubric requires booking and payment to be all-or-nothing, so the
        # payment and its link are inserted before the single commit below.
        payment_id = _gen_payment_id()
        cur.execute("""
            INSERT INTO payment_record (
                payment_id, amount_usd, method, status, paid_at
            )
            VALUES (%s, %s, 'credit_card', 'paid', %s)
            RETURNING payment_pk
        """, (payment_id, amount_usd, now))
        payment = cur.fetchone()

        cur.execute("""
            INSERT INTO national_rail_payment_record (payment_pk, booking_pk)
            VALUES (%s, %s)
        """, (payment['payment_pk'], booking['booking_pk']))

        conn.commit()
        result = dict(booking)
        result.update({
            "schedule_id": schedule_id,
            "origin_station_id": origin_station_id,
            "destination_station_id": destination_station_id,
            "departure_id": departure_id,
            "ticket_type": ticket_type,
            "fare_class": fare_class,
            "seat_id": seat_id,
            "payment_id": payment_id,
        })
        return True, _row_to_dict(result)

    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Booking failed: {str(e)}"
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()



def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.

    Calculates the refund amount according to the booking's service type:
      - Normal service: RF001 windows (100% / 75% / 50% / 0%)
      - Express service: RF002 windows (100% / 50% / 0%)

    Args:
        booking_id: e.g. "BK001"
        user_id:    must match the booking's user_id

    Returns:
        (True, result_dict)  with refund_amount_usd and policy note
        (False, error_msg)
    """
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch booking details and verify ownership
        cur.execute("""
            SELECT
                nrb.booking_pk,
                nrb.booking_id,
                up.user_id,
                nrb.amount_usd,
                nrb.travel_date,
                nrb.status,
                nrb.booked_at,
                ss.service_type,
                EXTRACT(EPOCH FROM (
                    (sd.service_date + sd.departure_time) - CURRENT_TIMESTAMP
                )) / 3600 AS hours_until_departure,
                original_payment.method AS payment_method
            FROM national_rail_booking nrb
            JOIN user_profiles up
                ON up.id = nrb.user_profile_id
            JOIN service_departures sd
                ON sd.service_departure_pk = nrb.service_departure_pk
            JOIN schedule_services ss ON ss.schedule_id = sd.schedule_id
            LEFT JOIN LATERAL (
                SELECT pr.method
                FROM national_rail_payment_record nrpr
                JOIN payment_record pr ON pr.payment_pk = nrpr.payment_pk
                WHERE nrpr.booking_pk = nrb.booking_pk
                  AND pr.status = 'paid'
                ORDER BY pr.paid_at DESC, pr.payment_pk DESC
                LIMIT 1
            ) original_payment ON TRUE
            WHERE nrb.booking_id = %s
            FOR UPDATE OF nrb
        """, (booking_id,))
        booking = cur.fetchone()

        if not booking:
            return False, f"Booking {booking_id} not found"

        # Verify user ownership
        if booking['user_id'] != user_id:
            return False, "Booking does not belong to this user"

        # Check if booking can be cancelled
        if booking['status'] != 'confirmed':
            return False, f"Cannot cancel booking with status '{booking['status']}'"

        hours_until_departure = max(
            Decimal(booking['hours_until_departure']),
            Decimal("0"),
        )

        # Determine refund policy and percentage based on service type and timing
        service_type = booking['service_type']
        
        if service_type in ('normal',):
            # RF001: Normal service refund windows
            if hours_until_departure >= 48:
                refund_percentage = 100
                admin_fee = Decimal("0.00")
                policy_note = "RF001: 48+ hours before departure (100% refund)"
            elif hours_until_departure >= 24:
                refund_percentage = 75
                admin_fee = Decimal("0.50")
                policy_note = "RF001: 24-48 hours before departure (75% refund, $0.50 fee)"
            elif hours_until_departure >= 2:
                refund_percentage = 50
                admin_fee = Decimal("0.50")
                policy_note = "RF001: 2-24 hours before departure (50% refund, $0.50 fee)"
            else:
                refund_percentage = 0
                admin_fee = Decimal("0.00")
                policy_note = "RF001: Less than 2 hours before departure (0% refund)"
        
        elif service_type in ('express',):
            # RF002: Express service refund windows
            if hours_until_departure >= 48:
                refund_percentage = 100
                admin_fee = Decimal("1.00")
                policy_note = "RF002: 48+ hours before departure (100% refund, $1.00 fee)"
            elif hours_until_departure >= 24:
                refund_percentage = 50
                admin_fee = Decimal("1.00")
                policy_note = "RF002: 24-48 hours before departure (50% refund, $1.00 fee)"
            else:
                refund_percentage = 0
                admin_fee = Decimal("0.00")
                policy_note = "RF002: Less than 24 hours before departure (0% refund)"
        
        else:
            # Default policy for unknown service types
            refund_percentage = 50
            admin_fee = Decimal("0.00")
            policy_note = f"Default policy: 50% refund for {service_type} service"

        # Calculate refund amount
        refund_amount = max(
            booking['amount_usd'] * Decimal(refund_percentage) / 100 - admin_fee,
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))

        # Update booking status to cancelled
        now = datetime.now(timezone.utc)
        cur.execute("""
            UPDATE national_rail_booking
            SET status = 'cancelled'
            WHERE booking_id = %s
            RETURNING booking_pk, booking_id, user_profile_id, status
        """, (booking_id,))
        
        cancelled_booking = cur.fetchone()
        if not cancelled_booking:
            conn.rollback()
            return False, "Failed to update booking status"

        # Release seat reservations for this booking
        cur.execute("""
            UPDATE seat_reservations
            SET reservation_status = 'cancelled'
            WHERE booking_id = %s
              AND reservation_status IN ('held', 'confirmed')
        """, (booking_id,))

        # Generate refund payment record if refund amount > 0
        if refund_amount > 0:
            if not booking['payment_method']:
                return False, "Cannot issue refund because no original payment was found"

            refund_payment_id = _gen_payment_id()
            cur.execute("""
                INSERT INTO payment_record (
                    payment_id, amount_usd, method, status, paid_at
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING payment_pk
            """, (
                refund_payment_id,
                refund_amount,
                booking['payment_method'],
                'refunded',
                now
            ))
            
            refund_payment = cur.fetchone()
            if refund_payment:
                # Link refund to the original booking
                cur.execute("""
                    INSERT INTO national_rail_payment_record (payment_pk, booking_pk)
                    VALUES (%s, %s)
                """, (refund_payment['payment_pk'], booking['booking_pk']))

        conn.commit()
        
        # Return cancellation result
        result = {
            'booking_id': booking_id,
            'original_amount_usd': float(booking['amount_usd']),
            'refund_percentage': refund_percentage,
            'admin_fee_usd': float(admin_fee),
            'refund_amount': float(refund_amount),
            'refund_amount_usd': float(refund_amount),
            'policy_note': policy_note,
            'cancelled_at': now.isoformat(),
            'hours_until_departure': float(hours_until_departure)
        }
        
        return True, result

    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Cancellation failed: {str(e)}"
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    Returns (True, user_id) on success or (False, error_message) on failure.

    NOTE: passwords are stored as plain text here intentionally for teaching
    purposes. In production, replace with a salted hash (e.g. bcrypt).
    """
    raise NotImplementedError("TODO: implement after designing your schema")


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    raise NotImplementedError("TODO: implement after designing your schema")


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    raise NotImplementedError("TODO: implement after designing your schema")


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    raise NotImplementedError("TODO: implement after designing your schema")


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    raise NotImplementedError("TODO: implement after designing your schema")


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]
