"""SkyPoints member-profile and redemption ETL reference implementation.

This is a correctness-focused, small-data PostgreSQL implementation. See README.md
for the production-scale architecture required for very high daily volumes.
"""

import hashlib
import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from src.utils import INVALID_DATE, calculate_age, calculate_stale_member, normalize_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))

DB_USER = os.getenv("DB_USER", os.getenv("USER", "postgres"))
DB_URL = os.getenv("DATABASE_URL", f"postgresql+psycopg2://{DB_USER}@localhost:5432/skypoints_db")
def get_engine():
    """Create the database engine only when the pipeline is executed (keeps unit tests DB-independent)."""
    return create_engine(DB_URL, pool_pre_ping=True)

# Every configured feed is required for this full-refresh run. Missing files fail preflight.
COUNTRY_FILES = {
    "USA": {"filenames": ["USA(in).csv", "USA.csv"], "type": "csv"},
    "IND": {"filenames": ["IND(in).csv", "IND.csv"], "type": "csv"},
    "AUS": {"filenames": ["AUS.xlsx"], "type": "excel"},
}
REDEMPTION_FILE = Path(os.getenv("REDEMPTION_FILE", DATA_DIR / "redemptions_sample.json"))
TARGET_TABLES = {"USA": "table_usa", "IND": "table_ind", "AUS": "table_aus", "AU": "table_aus", "PHIL": "table_phil", "CAN": "table_can"}
COUNTRY_CODES = {"USA", "IND", "AUS", "AU", "PHIL", "CAN"}


def clean_text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    result = str(value).strip()
    return result or None


def normalize_column_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def get_column(row, *aliases):
    lookup = {normalize_column_name(k): k for k in row.index}
    for alias in aliases:
        actual = lookup.get(normalize_column_name(alias))
        if actual is not None:
            return row[actual]
    return None


def json_safe_record(row):
    result = {}
    for key, value in row.items():
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            result[str(key)] = None
        elif hasattr(value, "isoformat"):
            result[str(key)] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
        else:
            result[str(key)] = str(value)
    return result


def preflight_inputs():
    """Resolve and validate every required input before opening a DB transaction."""
    resolved = {}
    errors = []
    for country, spec in COUNTRY_FILES.items():
        path = next((DATA_DIR / name for name in spec["filenames"] if (DATA_DIR / name).is_file()), None)
        if path is None:
            errors.append(f"Missing required {country} profile feed; expected one of {spec['filenames']}")
            continue
        if path.stat().st_size == 0:
            errors.append(f"Required profile feed is empty: {path.name}")
            continue
        resolved[country] = path
    if not REDEMPTION_FILE.is_file():
        errors.append(f"Missing required redemption JSON feed: {REDEMPTION_FILE}")
    elif REDEMPTION_FILE.stat().st_size == 0:
        errors.append(f"Required redemption JSON feed is empty: {REDEMPTION_FILE}")
    if errors:
        raise FileNotFoundError("Input preflight failed:\n- " + "\n- ".join(errors))
    return resolved


def read_profile_file(path, file_type):
    if file_type == "excel":
        return pd.read_excel(path, sheet_name=0, dtype=object)
    return pd.read_csv(path, dtype=object, keep_default_na=True)


def _optional_text(value, field, max_length, warnings):
    value = clean_text(value)
    if value is not None and len(value) > max_length:
        warnings.append(f"{field} exceeds maximum length {max_length}; stored as NULL")
        return None
    return value


def transform_source_row(row, country, filename, row_number):
    """Return (record, errors, warnings); optional-field problems never reject a row."""
    name = clean_text(get_column(row, "Member Name", "Name"))
    member_id = clean_text(get_column(row, "Unique ID", "Member ID", "ID"))
    tier = clean_text(get_column(row, "Tier Type", "Tier Code", "TierCode"))
    dob_raw = clean_text(get_column(row, "Date of Birth", "DOB"))
    enrollment_raw = clean_text(get_column(row, "Date of Enrollment", "Enrollment Date", "EnrollmentDate"))
    flight_raw = clean_text(get_column(row, "Date of Flight", "Flight Date", "FlightDate", "Last Flight Date"))

    errors, warnings = [], []
    if not name:
        errors.append("Member Name is mandatory but missing")
    elif len(name) > 255:
        errors.append("Member Name exceeds maximum length 255")
    if not member_id:
        errors.append("Member ID is mandatory but missing")
    elif len(member_id) > 18:
        errors.append("Member ID exceeds maximum length 18")

    enrollment = normalize_date(enrollment_raw)
    if enrollment is None:
        errors.append("Enrollment Date is mandatory but missing")
    elif enrollment == INVALID_DATE:
        errors.append(f"Invalid Enrollment Date: {enrollment_raw}")

    # Optional dates: preserve the member; null the bad field and record a warning.
    dob = normalize_date(dob_raw)
    if dob == INVALID_DATE:
        warnings.append(f"Invalid optional Date of Birth '{dob_raw}'; stored as NULL")
        dob = None
    flight = normalize_date(flight_raw)
    if flight == INVALID_DATE:
        warnings.append(f"Invalid optional Flight Date '{flight_raw}'; stored as NULL")
        flight = None

    tier = _optional_text(tier, "Tier Code", 5, warnings)
    agent = _optional_text(get_column(row, "Agent Name", "Agent_Name"), "Agent Name", 255, warnings)
    state = _optional_text(get_column(row, "State"), "State", 5, warnings)
    source_country_value = clean_text(get_column(row, "Country"))
    member_country = (source_country_value or country or "").upper()
    if member_country and member_country not in COUNTRY_CODES:
        errors.append(f"Unsupported Country code: {member_country}")
    if member_country == "AU":
        warnings.append("Country code AU retained from source; routed to Australia target (AUS)")

    post_raw = clean_text(get_column(row, "Post Code", "PostCode", "Postal Code"))
    post_code = None
    if post_raw:
        if not re.fullmatch(r"\d{1,5}", post_raw):
            warnings.append(f"Invalid optional Post Code '{post_raw}'; stored as NULL (expected up to 5 digits)")
        else:
            post_code = int(post_raw)

    active = _optional_text(get_column(row, "Is Active", "Active Member", "Is_Active"), "Active Member", 1, warnings)
    individual = _optional_text(get_column(row, "Individual or Corporate", "Individual_or_Corporate"), "Individual or Corporate", 20, warnings)

    record = {
        "source_file": filename, "source_country": country, "source_row_number": row_number,
        "member_id": member_id, "member_name": name, "tier_code": tier,
        "dob_raw": dob_raw, "enrollment_date_raw": enrollment_raw, "flight_date_raw": flight_raw,
        "dob": dob if isinstance(dob, date) else None,
        "enrollment_date": enrollment if isinstance(enrollment, date) else None,
        "flight_date": flight if isinstance(flight, date) else None,
        "agent_name": agent, "state": state, "country": member_country or None,
        "post_code": post_code, "is_active": active, "individual_or_corporate": individual,
        "age": calculate_age(dob) if isinstance(dob, date) else None,
        "is_stale_member": calculate_stale_member(flight) if isinstance(flight, date) else None,
    }
    return record, errors, warnings


def extract_member_records(resolved_files):
    raw_records, accepted, rejected, quality_warnings = [], [], [], []
    for country, path in resolved_files.items():
        file_type = COUNTRY_FILES[country]["type"]
        frame = read_profile_file(path, file_type)
        if frame.empty:
            raise ValueError(f"Required profile feed has headers but no data rows: {path.name}")
        for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
            raw = json_safe_record(row.to_dict())
            raw_records.append({"source_file": path.name, "source_country": country, "source_row_number": row_number, "raw_record": raw})
            record, errors, warnings = transform_source_row(row, country, path.name, row_number)
            for warning in warnings:
                quality_warnings.append({"source_file": path.name, "source_country": country, "source_row_number": row_number, "issue_type": "WARNING", "issue_detail": warning})
            if errors:
                rejected.append({"source_file": path.name, "source_country": country, "source_row_number": row_number, "raw_record": raw, "rejection_reason": "; ".join(errors)})
            else:
                accepted.append(record)
    return raw_records, accepted, rejected, quality_warnings


def load_json_feeds(path):
    """Read one JSON object or an array of feed objects; no payload is hardcoded in ETL code."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    feeds = payload if isinstance(payload, list) else [payload]
    if not feeds or any(not isinstance(feed, dict) for feed in feeds):
        raise ValueError("Redemption JSON must be an object or a non-empty array of feed objects")
    return feeds


def validate_and_flatten_redemptions(feeds):
    flattened, issues = [], []
    for feed_index, feed in enumerate(feeds, start=1):
        member_id = clean_text(feed.get("member_id"))
        feed_date = normalize_date(feed.get("feed_date"))
        feed_errors = []
        if not member_id:
            feed_errors.append("member_id is mandatory")
        elif len(member_id) > 18:
            feed_errors.append("member_id exceeds maximum length 18")
        if not isinstance(feed_date, date):
            feed_errors.append("feed_date is missing or invalid")
        redemptions = feed.get("redemptions")
        if not isinstance(redemptions, list):
            feed_errors.append("redemptions must be an array")
            redemptions = []
        if feed_errors:
            issues.append({"source_file": str(REDEMPTION_FILE.name), "source_country": None, "source_row_number": feed_index, "issue_type": "REJECTED_FEED", "issue_detail": "; ".join(feed_errors)})
            continue
        for item_index, item in enumerate(redemptions, start=1):
            errors = []
            if not isinstance(item, dict):
                errors.append("redemption item must be an object")
                item = {}
            txn_id = clean_text(item.get("txn_id"))
            txn_date = normalize_date(item.get("txn_date"))
            partner = clean_text(item.get("partner"))
            status = clean_text(item.get("status"))
            miles = item.get("miles_redeemed")
            if not txn_id:
                errors.append("txn_id is mandatory")
            elif len(txn_id) > 50:
                errors.append("txn_id exceeds maximum length 50")
            if not isinstance(txn_date, date):
                errors.append("txn_date is missing or invalid")
            if not partner:
                errors.append("partner is mandatory")
            elif len(partner) > 100:
                errors.append("partner exceeds maximum length 100")
            if isinstance(miles, bool) or not isinstance(miles, int) or miles < 0:
                errors.append("miles_redeemed must be a non-negative integer")
            if not status:
                errors.append("status is mandatory")
            elif len(status) > 30:
                errors.append("status exceeds maximum length 30")
            if errors:
                issues.append({"source_file": REDEMPTION_FILE.name, "source_country": None, "source_row_number": feed_index, "issue_type": "REJECTED_REDEMPTION", "issue_detail": f"feed {feed_index}, redemption {item_index}: " + "; ".join(errors)})
                continue
            flattened.append({"txn_id": txn_id, "member_id": member_id, "txn_date": txn_date, "partner": partner, "miles_redeemed": miles, "status": status, "feed_date": feed_date})
    return flattened, issues


def _insert_many(conn, sql, rows):
    if rows:
        conn.execute(text(sql), rows)


def persist_raw_and_profile_quality(conn, raw_records, rejected, warnings):
    _insert_many(conn, """INSERT INTO skypoints.raw_member_profiles (source_file, source_country, source_row_number, raw_record) VALUES (:source_file, :source_country, :source_row_number, CAST(:raw_record AS JSONB))""", [dict(x, raw_record=json.dumps(x["raw_record"])) for x in raw_records])
    _insert_many(conn, """INSERT INTO skypoints.removed_records (source_file, source_country, source_row_number, raw_record, rejection_reason) VALUES (:source_file, :source_country, :source_row_number, CAST(:raw_record AS JSONB), :rejection_reason)""", [dict(x, raw_record=json.dumps(x["raw_record"])) for x in rejected])
    _insert_many(conn, """INSERT INTO skypoints.data_quality_issues (source_file, source_country, source_row_number, issue_type, issue_detail) VALUES (:source_file, :source_country, :source_row_number, :issue_type, :issue_detail)""", warnings)


def persist_redemptions(conn, feeds, flattened, issues):
    raw_rows = [{"source_file": REDEMPTION_FILE.name, "payload": json.dumps(feed), "payload_hash": hashlib.sha256(json.dumps(feed, sort_keys=True).encode()).hexdigest()} for feed in feeds]
    _insert_many(conn, """INSERT INTO skypoints.raw_redemptions_json (source_file, payload, payload_hash) VALUES (:source_file, CAST(:payload AS JSONB), :payload_hash) ON CONFLICT (payload_hash) DO NOTHING""", raw_rows)
    # Same transaction ID + identical content is a harmless replay; conflicting content is quarantined.
    for row in flattened:
        existing = conn.execute(text("SELECT member_id, txn_date, partner, miles_redeemed, status, feed_date FROM skypoints.fact_redemptions WHERE txn_id=:txn_id"), {"txn_id": row["txn_id"]}).mappings().first()
        if existing:
            same = all(existing[k] == row[k] for k in ("member_id", "txn_date", "partner", "miles_redeemed", "status", "feed_date"))
            if not same:
                issues.append({"source_file": REDEMPTION_FILE.name, "source_country": None, "source_row_number": None, "issue_type": "CONFLICTING_DUPLICATE_TXN", "issue_detail": f"txn_id {row['txn_id']} already exists with different transaction values"})
            continue
        conn.execute(text("""INSERT INTO skypoints.fact_redemptions (txn_id, member_id, txn_date, partner, miles_redeemed, status, feed_date) VALUES (:txn_id, :member_id, :txn_date, :partner, :miles_redeemed, :status, :feed_date)"""), row)
    _insert_many(conn, """INSERT INTO skypoints.redemption_issues (source_file, source_row_number, issue_type, issue_detail) VALUES (:source_file, :source_row_number, :issue_type, :issue_detail)""", [x for x in issues if x["issue_type"].startswith("REJECTED_") or x["issue_type"] == "CONFLICTING_DUPLICATE_TXN"])


def load_staging(conn, records):
    if not records:
        return
    pd.DataFrame(records).to_sql("stg_member_profiles", conn, schema="skypoints", if_exists="append", index=False, method="multi", chunksize=1000)


def route_members_latest_wins(conn):
    """Assessment key is Member Name; Enrollment Date is the primary recency proxy."""
    winners = conn.execute(text("""
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY LOWER(BTRIM(member_name))
                ORDER BY enrollment_date DESC, flight_date DESC NULLS LAST,
                         source_country ASC, source_row_number DESC
            ) AS rn
            FROM skypoints.stg_member_profiles
        )
        SELECT * FROM ranked WHERE rn=1
    """)).mappings().all()

    for table in TARGET_TABLES.values():
        conn.execute(text(f"TRUNCATE TABLE skypoints.{table}"))

    columns = ("member_name", "member_id", "tier_code", "enrollment_date", "flight_date", "dob", "agent_name", "state", "country", "post_code", "is_active", "individual_or_corporate", "age", "is_stale_member", "source_file")
    for member in winners:
        country = (member["country"] or member["source_country"] or "").strip().upper()
        table = TARGET_TABLES.get(country)
        if not table:
            # This should have been caught during row validation; fail the transaction rather than lose a row.
            raise ValueError(f"No target table configured for country {country!r}, member {member['member_name']!r}")
        names = ", ".join(columns)
        binds = ", ".join(f":{column}" for column in columns)
        conn.execute(text(f"INSERT INTO skypoints.{table} ({names}) VALUES ({binds})"), {column: member[column] for column in columns})


def main():
    logging.info("Starting SkyPoints pipeline")
    resolved_files = preflight_inputs()  # Must complete before any DB mutation.
    raw, accepted, rejected, warnings = extract_member_records(resolved_files)
    feeds = load_json_feeds(REDEMPTION_FILE)
    flattened, redemption_issues = validate_and_flatten_redemptions(feeds)
    logging.info("Profiles: %d raw, %d accepted, %d rejected, %d warnings", len(raw), len(accepted), len(rejected), len(warnings))
    logging.info("Redemptions: %d valid transactions, %d issues", len(flattened), len(redemption_issues))

    with get_engine().begin() as conn:
        # Full-refresh profile outputs. Do not truncate until every source has passed preflight and parsing.
        conn.execute(text("""TRUNCATE TABLE skypoints.table_usa, skypoints.table_ind, skypoints.table_aus, skypoints.table_phil, skypoints.table_can, skypoints.raw_member_profiles, skypoints.removed_records, skypoints.data_quality_issues, skypoints.stg_member_profiles RESTART IDENTITY"""))
        persist_raw_and_profile_quality(conn, raw, rejected, warnings)
        load_staging(conn, accepted)
        route_members_latest_wins(conn)
        # Redemption tables are incrementally/idempotently loaded, not truncated on each profile refresh.
        persist_redemptions(conn, feeds, flattened, redemption_issues)
    logging.info("SkyPoints pipeline completed successfully")


if __name__ == "__main__":
    main()
