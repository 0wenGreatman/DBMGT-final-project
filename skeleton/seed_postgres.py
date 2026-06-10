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
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values
from argon2 import PasswordHasher

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


NETWORK_IDS = {
    "metro": "M",
    "national_rail": "N",
}

NETWORK_NAMES = {
    "M": "Metro",
    "N": "National Rail",
}

FARE_EFFECTIVE_FROM = "2024-01-01"


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


def _usd(value):
    """Convert JSON numeric values to Decimal for DECIMAL columns."""
    if value is None:
        return None
    return Decimal(str(value))


def _fetch_map(cur, table, key_column, value_column):
    cur.execute(
        f"SELECT {key_column}, {value_column} FROM {table}"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _ticket_notes(details):
    """Keep extra ticket policy details without adding more table columns yet."""
    note_keys = (
        "formula",
        "validity",
        "outbound_validity",
        "return_validity",
        "refund_rule",
        "notes",
    )
    notes = []
    for key in note_keys:
        value = details.get(key)
        if value:
            notes.append(f"{key}: {value}")
    return " | ".join(notes) or None


def _seed_ticket_catalog(cur):
    """Seed ticket master rows and network availability used by fare_rules."""
    data = load("ticket_types.json")

    ticket_rows = [
        (
            item["ticket_type"],
            item["display_name"],
            item.get("description"),
        )
        for item in data
    ]
    insert_many(
        cur,
        "ticket_types",
        ["ticket_type_id", "display_name", "description"],
        ticket_rows,
    )

    network_rows = []
    for item in data:
        for source_network in item.get("available_on", []):
            network_id = NETWORK_IDS[source_network]
            details = item[source_network]
            network_rows.append(
                (
                    item["ticket_type"],
                    network_id,
                    bool(details.get("seat_assignment", False)),
                    bool(details.get("advance_purchase", False)),
                    details.get("advance_purchase_max_days"),
                    bool(details.get("changes_allowed", False)),
                    _usd(details.get("change_fee_usd")),
                    bool(details.get("refundable", False)),
                    _ticket_notes(details),
                )
            )

    insert_many(
        cur,
        "ticket_type_networks",
        [
            "ticket_type_id",
            "network_id",
            "seat_assignment",
            "advance_purchase",
            "advance_purchase_max_days",
            "changes_allowed",
            "change_fee_usd",
            "refundable",
            "notes",
        ],
        network_rows,
    )


def _departure_id(schedule_id, service_date, departure_time):
    """Build a compact service departure ID that also fits booking FKs."""
    schedule_key = (
        schedule_id
        .replace("NR_SCH", "N")
        .replace("MS_SCH", "M")
    )
    date_key = service_date[2:].replace("-", "")
    time_key = departure_time.replace(":", "")
    return f"D_{schedule_key}_{date_key}_{time_key}"


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    network_id = NETWORK_IDS["metro"]

    # Seed the network first because stations and lines depend on it.
    insert_many(
        cur,
        "networks",
        ["network_id", "network_display_name"],
        [(network_id, NETWORK_NAMES[network_id])],
    )

    station_rows = [
        (
            item["station_id"],
            network_id,
            item["name"],
        )
        for item in data
    ]
    insert_many(
        cur,
        "stations",
        ["station_id", "network_id", "station_name"],
        station_rows,
    )

    # Lines are derived from the station membership list in the mock data.
    line_ids = sorted({line_id for item in data for line_id in item["lines"]})
    line_rows = [
        (
            line_id,
            network_id,
            f"Metro Line {line_id}",
        )
        for line_id in line_ids
    ]
    insert_many(
        cur,
        "lines",
        ["line_id", "network_id", "line_name"],
        line_rows,
    )

    station_line_rows = [
        (
            item["station_id"],
            line_id,
        )
        for item in data
        for line_id in item["lines"]
    ]
    insert_many(
        cur,
        "station_lines",
        ["station_id", "line_id"],
        station_line_rows,
    )


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    network_id = NETWORK_IDS["national_rail"]

    # Seed the network first because stations and lines depend on it.
    insert_many(
        cur,
        "networks",
        ["network_id", "network_display_name"],
        [(network_id, NETWORK_NAMES[network_id])],
    )

    station_rows = [
        (
            item["station_id"],
            network_id,
            item["name"],
        )
        for item in data
    ]
    insert_many(
        cur,
        "stations",
        ["station_id", "network_id", "station_name"],
        station_rows,
    )

    # Lines are derived from the station membership list in the mock data.
    line_ids = sorted({line_id for item in data for line_id in item["lines"]})
    line_rows = [
        (
            line_id,
            network_id,
            f"National Rail Line {line_id}",
        )
        for line_id in line_ids
    ]
    insert_many(
        cur,
        "lines",
        ["line_id", "network_id", "line_name"],
        line_rows,
    )

    station_line_rows = [
        (
            item["station_id"],
            line_id,
        )
        for item in data
        for line_id in item["lines"]
    ]
    insert_many(
        cur,
        "station_lines",
        ["station_id", "line_id"],
        station_line_rows,
    )


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    _seed_ticket_catalog(cur)

    schedule_rows = [
        (
            item["schedule_id"],
            item["line"],
            "metro",
            item["direction"],
            item["origin_station_id"],
            item["destination_station_id"],
            item["first_train_time"],
            item["last_train_time"],
            item["frequency_min"],
        )
        for item in data
    ]
    insert_many(
        cur,
        "schedule_services",
        [
            "schedule_id",
            "line_id",
            "service_type",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "frequency_min",
        ],
        schedule_rows,
    )

    # Store one ordered stop row per station in each timetable.
    stop_rows = []
    operating_day_rows = []
    for item in data:
        travel_times = item.get("travel_time_from_origin_min", {})
        for sequence, station_id in enumerate(item["stops_in_order"], start=1):
            stop_rows.append(
                (
                    item["schedule_id"],
                    item["line"],
                    station_id,
                    sequence,
                    travel_times.get(station_id),
                )
            )
        for day_of_week in item.get("operates_on", []):
            operating_day_rows.append((item["schedule_id"], day_of_week))

    insert_many(
        cur,
        "schedule_stops",
        [
            "schedule_id",
            "line_id",
            "station_id",
            "stop_sequence",
            "travel_time_from_origin_min",
        ],
        stop_rows,
    )
    insert_many(
        cur,
        "schedule_operating_days",
        ["schedule_id", "day_of_week"],
        operating_day_rows,
    )

    fare_rows = [
        (
            f"FR_{item['schedule_id']}_SINGLE",
            NETWORK_IDS["metro"],
            item["schedule_id"],
            "single",
            None,
            "stops_based",
            _usd(item.get("base_fare_usd")),
            _usd(item.get("per_stop_rate_usd")),
            None,
            FARE_EFFECTIVE_FROM,
        )
        for item in data
    ]

    # The metro day pass is a flat rule and is not tied to one schedule.
    ticket_types = load("ticket_types.json")
    day_pass = next(
        item for item in ticket_types if item["ticket_type"] == "day_pass"
    )
    fare_rows.append(
        (
            "FR_M_DAY_PASS",
            NETWORK_IDS["metro"],
            None,
            "day_pass",
            None,
            "flat_rate",
            None,
            None,
            _usd(day_pass["metro"].get("price_usd")),
            FARE_EFFECTIVE_FROM,
        )
    )

    insert_many(
        cur,
        "fare_rules",
        [
            "fare_rule_code",
            "network_id",
            "schedule_id",
            "ticket_type_id",
            "fare_class_id",
            "pricing_model",
            "base_fare_usd",
            "per_stop_rate_usd",
            "price_usd",
            "effective_from",
        ],
        fare_rows,
    )


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    _seed_ticket_catalog(cur)

    schedule_rows = [
        (
            item["schedule_id"],
            item["line"],
            item["service_type"],
            item["direction"],
            item["origin_station_id"],
            item["destination_station_id"],
            item["first_train_time"],
            item["last_train_time"],
            item["frequency_min"],
        )
        for item in data
    ]
    insert_many(
        cur,
        "schedule_services",
        [
            "schedule_id",
            "line_id",
            "service_type",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "frequency_min",
        ],
        schedule_rows,
    )

    stop_rows = []
    operating_day_rows = []
    fare_class_ids = set()
    for item in data:
        travel_times = item.get("travel_time_from_origin_min", {})
        fare_class_ids.update(item.get("fare_classes", {}).keys())
        for sequence, station_id in enumerate(item["stops_in_order"], start=1):
            stop_rows.append(
                (
                    item["schedule_id"],
                    item["line"],
                    station_id,
                    sequence,
                    travel_times.get(station_id),
                )
            )
        for day_of_week in item.get("operates_on", []):
            operating_day_rows.append((item["schedule_id"], day_of_week))

    insert_many(
        cur,
        "schedule_stops",
        [
            "schedule_id",
            "line_id",
            "station_id",
            "stop_sequence",
            "travel_time_from_origin_min",
        ],
        stop_rows,
    )
    insert_many(
        cur,
        "schedule_operating_days",
        ["schedule_id", "day_of_week"],
        operating_day_rows,
    )

    # Fare classes must exist before fare_rules and coach rows reference them.
    fare_class_rows = [
        (
            fare_class_id,
            NETWORK_IDS["national_rail"],
            fare_class_id.replace("_", " ").title(),
        )
        for fare_class_id in sorted(fare_class_ids)
    ]
    insert_many(
        cur,
        "fare_classes",
        ["fare_class_id", "network_id", "class_display_name"],
        fare_class_rows,
    )

    fare_rows = []
    for item in data:
        for fare_class_id, fare_detail in item.get("fare_classes", {}).items():
            for ticket_type_id, pricing_model in (
                ("single", "stops_based_with_fare_class"),
                ("return", "stops_based_per_leg"),
            ):
                fare_rows.append(
                    (
                        (
                            f"FR_{item['schedule_id']}_"
                            f"{ticket_type_id.upper()}_{fare_class_id.upper()}"
                        ),
                        NETWORK_IDS["national_rail"],
                        item["schedule_id"],
                        ticket_type_id,
                        fare_class_id,
                        pricing_model,
                        _usd(fare_detail.get("base_fare_usd")),
                        _usd(fare_detail.get("per_stop_rate_usd")),
                        None,
                        FARE_EFFECTIVE_FROM,
                    )
                )

    insert_many(
        cur,
        "fare_rules",
        [
            "fare_rule_code",
            "network_id",
            "schedule_id",
            "ticket_type_id",
            "fare_class_id",
            "pricing_model",
            "base_fare_usd",
            "per_stop_rate_usd",
            "price_usd",
            "effective_from",
        ],
        fare_rows,
    )


def seed_service_departures(cur):
    """Seed concrete national rail departures observed in the mock bookings."""
    data = load("bookings.json")

    # bookings.json is the only mock file with explicit concrete train dates
    # and departure times. Use it only to derive schedule instances here.
    departure_rows = sorted(
        {
            (
                _departure_id(
                    item["schedule_id"],
                    item["travel_date"],
                    item["departure_time"],
                ),
                item["schedule_id"],
                item["travel_date"],
                item["departure_time"],
                "scheduled",
            )
            for item in data
        }
    )
    insert_many(
        cur,
        "service_departures",
        [
            "departure_id",
            "schedule_id",
            "service_date",
            "departure_time",
            "status",
        ],
        departure_rows,
    )


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    layout_rows = [
        (
            item["layout_id"],
            item["schedule_id"],
        )
        for item in data
    ]
    insert_many(
        cur,
        "seat_layouts",
        ["layout_code", "schedule_id"],
        layout_rows,
    )

    cur.execute("SELECT seat_layout_pk, layout_code FROM seat_layouts")
    layout_pk_by_code = {layout_code: row_id for row_id, layout_code in cur.fetchall()}

    coach_rows = []
    seat_rows = []
    for item in data:
        layout_code = item["layout_id"]
        layout_pk = layout_pk_by_code[layout_code]
        for coach in item.get("coaches", []):
            coach_code = coach["coach"]
            coach_rows.append(
                (
                    layout_pk,
                    coach_code,
                    coach["fare_class"],
                )
            )

            for seat in coach.get("seats", []):
                seat_rows.append(
                    (
                        layout_code,
                        coach_code,
                        seat["seat_id"],
                        seat.get("row"),
                        seat.get("column"),
                    )
                )

    insert_many(
        cur,
        "coaches",
        ["seat_layout_pk", "coach_code", "fare_class_id"],
        coach_rows,
    )

    cur.execute(
        """
        SELECT c.coach_pk, sl.layout_code, c.coach_code
        FROM coaches c
        JOIN seat_layouts sl
            ON sl.seat_layout_pk = c.seat_layout_pk
        """
    )
    coach_pk_by_layout_and_code = {
        (layout_code, coach_code): coach_pk
        for coach_pk, layout_code, coach_code in cur.fetchall()
    }

    seat_rows = [
        (
            coach_pk_by_layout_and_code[(layout_code, coach_code)],
            seat_code,
            seat_row,
            seat_column,
        )
        for layout_code, coach_code, seat_code, seat_row, seat_column in seat_rows
    ]
    insert_many(
        cur,
        "seats",
        ["coach_pk", "seat_code", "seat_row", "seat_column"],
        seat_rows,
    )


def seed_seat_reservations(cur):
    data = load("bookings.json")
    schedules = load("national_rail_schedules.json")

    cur.execute(
        """
        SELECT s.seat_pk, sl.schedule_id, c.coach_code, s.seat_code
        FROM seats s
        JOIN coaches c
            ON c.coach_pk = s.coach_pk
        JOIN seat_layouts sl
            ON sl.seat_layout_pk = c.seat_layout_pk
        """
    )
    seat_pk_by_schedule_coach_and_code = {
        (schedule_id, coach_code, seat_code): seat_pk
        for seat_pk, schedule_id, coach_code, seat_code in cur.fetchall()
    }

    # The reservation table stores stop sequence numbers for the booked segment.
    # Rebuild those sequence numbers from the schedule stop order in the JSON.
    stop_sequence_by_schedule = {
        item["schedule_id"]: {
            station_id: sequence
            for sequence, station_id in enumerate(item["stops_in_order"], start=1)
        }
        for item in schedules
    }

    reservation_rows = []
    for item in data:
        booking_id = item["booking_id"]
        schedule_id = item["schedule_id"]
        stop_sequences = stop_sequence_by_schedule.get(schedule_id)

        if not stop_sequences:
            raise ValueError(f"No stop sequence found for schedule {schedule_id}")

        origin_station_id = item["origin_station_id"]
        destination_station_id = item["destination_station_id"]
        origin_sequence = stop_sequences.get(origin_station_id)
        destination_sequence = stop_sequences.get(destination_station_id)

        if origin_sequence is None or destination_sequence is None:
            raise ValueError(
                f"Booking {booking_id} has stations outside schedule {schedule_id}"
            )

        seat_pk = seat_pk_by_schedule_coach_and_code.get(
            (schedule_id, item["coach"], item["seat_id"])
        )
        if seat_pk is None:
            raise ValueError(
                f"No seat found for booking {booking_id}: "
                f"{schedule_id}/{item['coach']}/{item['seat_id']}"
            )

        reservation_rows.append(
            (
                _departure_id(
                    schedule_id,
                    item["travel_date"],
                    item["departure_time"],
                ),
                seat_pk,
                booking_id,
                origin_station_id,
                destination_station_id,
                origin_sequence,
                destination_sequence,
                item["status"],
                None,
            )
        )

    insert_many(
        cur,
        "seat_reservations",
        [
            "departure_id",
            "seat_pk",
            "booking_id",
            "origin_station_id",
            "destination_station_id",
            "origin_stop_sequence",
            "destination_stop_sequence",
            "reservation_status",
            "held_until",
        ],
        reservation_rows,
    )


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
        
    if log_rows:
        sql = (
            "INSERT INTO login_logs (user_profile_id, login_at, status) "
            "SELECT v.user_profile_id::uuid, v.login_at::timestamp, v.status::login_status_enum "
            "FROM (VALUES %s) AS v(user_profile_id, login_at, status) "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM login_logs l "
            "  WHERE l.user_profile_id = v.user_profile_id::uuid "
            "    AND l.login_at = v.login_at::timestamp "
            "    AND l.status = v.status::login_status_enum"
            ")"
        )
        execute_values(cur, sql, log_rows)


def seed_national_rail_bookings(cur):
    data = load("bookings.json")

    station_map = _fetch_map(cur, "stations", "station_id", "station_pk")
    departure_map = _fetch_map(cur, "service_departures", "departure_id", "service_departure_pk")
    ticket_type_map = _fetch_map(cur, "ticket_types", "ticket_type_id", "ticket_type_pk")

    rows = []
    for item in data:
        departure_id = _departure_id(
            item["schedule_id"], item["travel_date"], item["departure_time"]
        )
        rows.append(
            (
                item["booking_id"],
                item["user_id"],
                station_map[item["origin_station_id"]],
                station_map[item["destination_station_id"]],
                item["travel_date"],
                departure_map[departure_id],
                ticket_type_map[item["ticket_type"]],
                _usd(item.get("amount_usd")),
                item.get("status"),
                item.get("booked_at"),
                item.get("travelled_at"),
            )
        )

    insert_many(
        cur,
        "national_rail_booking",
        [
            "booking_id",
            "user_id",
            "origin_station_pk",
            "destination_station_pk",
            "travel_date",
            "service_departure_pk",
            "ticket_type_pk",
            "amount_usd",
            "status",
            "booked_at",
            "travelled_at",
        ],
        rows,
    )


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")

    schedule_map = _fetch_map(cur, "schedule_services", "schedule_id", "schedule_service_pk")
    station_map = _fetch_map(cur, "stations", "station_id", "station_pk")
    ticket_type_map = _fetch_map(cur, "ticket_types", "ticket_type_id", "ticket_type_pk")

    parent_rows = []
    child_rows = []
    for item in data:
        row = (
            item["trip_id"],
            item["user_id"],
            schedule_map[item["schedule_id"]],
            station_map[item["origin_station_id"]],
            station_map[item["destination_station_id"]],
            item["travel_date"],
            ticket_type_map[item["ticket_type"]],
            item.get("day_pass_ref"),
            item.get("stops_travelled"),
            _usd(item.get("amount_usd")),
            item.get("status"),
            item.get("purchased_at"),
            item.get("travelled_at"),
        )
        if item.get("day_pass_ref"):
            child_rows.append(row)
        else:
            parent_rows.append(row)

    insert_many(
        cur,
        "metro_booking",
        [
            "trip_id",
            "user_id",
            "schedule_service_pk",
            "origin_station_pk",
            "destination_station_pk",
            "travel_date",
            "ticket_type_pk",
            "day_pass_ref",
            "stops_travelled",
            "amount_usd",
            "status",
            "purchased_at",
            "travelled_at",
        ],
        parent_rows,
    )

    if child_rows:
        insert_many(
            cur,
            "metro_booking",
            [
                "trip_id",
                "user_id",
                "schedule_service_pk",
                "origin_station_pk",
                "destination_station_pk",
                "travel_date",
                "ticket_type_pk",
                "day_pass_ref",
                "stops_travelled",
                "amount_usd",
                "status",
                "purchased_at",
                "travelled_at",
            ],
            child_rows,
        )


def seed_payments(cur):
    data = load("payments.json")

    base_rows = []
    for item in data:
        base_rows.append(
            (
                item["payment_id"],
                _usd(item.get("amount_usd")),
                item.get("method"),
                item.get("status"),
                item.get("paid_at"),
            )
        )

    insert_many(
        cur,
        "payment_record",
        ["payment_id", "amount_usd", "method", "status", "paid_at"],
        base_rows,
    )

    payment_map = _fetch_map(cur, "payment_record", "payment_id", "payment_pk")
    booking_map = _fetch_map(cur, "national_rail_booking", "booking_id", "booking_pk")
    trip_map = _fetch_map(cur, "metro_booking", "trip_id", "trip_pk")

    nr_rows = []
    metro_rows = []
    metro_payment_by_trip_ref = {}
    for item in data:
        payment_pk = payment_map[item["payment_id"]]
        booking_ref = item.get("booking_id")
        if booking_ref and booking_ref.upper().startswith("BK"):
            nr_rows.append((payment_pk, booking_map[booking_ref]))
        elif booking_ref and booking_ref.upper().startswith("MT"):
            metro_rows.append((payment_pk, trip_map[booking_ref]))
            metro_payment_by_trip_ref[booking_ref] = payment_pk

    # A day-pass purchase pays for its later zero-cost trips as well, so those
    # trips share the parent's payment association.
    for trip in load("metro_travel_history.json"):
        day_pass_ref = trip.get("day_pass_ref")
        if day_pass_ref and day_pass_ref in metro_payment_by_trip_ref:
            metro_rows.append(
                (metro_payment_by_trip_ref[day_pass_ref], trip_map[trip["trip_id"]])
            )

    if nr_rows:
        insert_many(
            cur,
            "national_rail_payment_record",
            ["payment_pk", "booking_pk"],
            nr_rows,
        )
    if metro_rows:
        insert_many(
            cur,
            "metro_payment_record",
            ["payment_pk", "trip_pk"],
            metro_rows,
        )


def seed_feedback(cur):
    data = load("feedback.json")

    base_rows = []
    for item in data:
        base_rows.append(
            (
                item["feedback_id"],
                item.get("user_id"),
                item.get("rating"),
                item.get("comment"),
                item.get("submitted_at"),
            )
        )

    insert_many(
        cur,
        "feedback_base",
        ["feedback_id", "user_id", "rating", "comment", "submitted_at"],
        base_rows,
    )

    feedback_map = _fetch_map(cur, "feedback_base", "feedback_id", "feedback_pk")
    booking_map = _fetch_map(cur, "national_rail_booking", "booking_id", "booking_pk")
    trip_map = _fetch_map(cur, "metro_booking", "trip_id", "trip_pk")

    nr_rows = []
    metro_rows = []
    for item in data:
        feedback_pk = feedback_map[item["feedback_id"]]
        booking_ref = item.get("booking_id")
        if booking_ref and booking_ref.upper().startswith("BK"):
            nr_rows.append((feedback_pk, booking_map[booking_ref]))
        elif booking_ref and booking_ref.upper().startswith("MT"):
            metro_rows.append((feedback_pk, trip_map[booking_ref]))

    if nr_rows:
        insert_many(
            cur,
            "national_rail_feedback",
            ["feedback_pk", "booking_pk"],
            nr_rows,
        )
    if metro_rows:
        insert_many(
            cur,
            "metro_feedback",
            ["feedback_pk", "trip_pk"],
            metro_rows,
        )
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
        seed_service_departures(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_seat_reservations(cur)
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
