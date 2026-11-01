
"""Batch-oriented SkyPoints profile and redemption pipeline."""
import hashlib
import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from src.utils import (
    INVALID_DATE,
    calculate_age,
    calculate_stale_member,
    normalize_date,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE / "data"))

DB_USER = os.getenv("DB_USER", os.getenv("USER", "postgres"))
DB_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg2://{DB_USER}@localhost:5432/skypoints_db",
)

COUNTRY_FILES = {
    "USA": {"filenames": ["USA(in).csv", "USA.csv"], "type": "csv"},
    "IND": {"filenames": ["IND(in).csv", "IND.csv"], "type": "csv"},
    "AUS": {"filenames": ["AUS.xlsx"], "type": "excel"},
}

REDEMPTION_FILE = Path(
    os.getenv("REDEMPTION_FILE", DATA_DIR / "redemptions_sample.json")
)

TARGET_TABLES = {
    "USA": "table_usa",
    "IND": "table_ind",
    "AUS": "table_aus",
    "AU": "table_aus",
    "PHIL": "table_phil",
    "CAN": "table_can",
}

COUNTRY_CODES = set(TARGET_TABLES)


def get_engine():
    return create_engine(DB_URL, pool_pre_ping=True)


def clean_text(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    value = str(value).strip()
    return value or None


def normalize_column_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def get_column(row, *aliases):
    lookup = {
        normalize_column_name(k): k
        for k in row.index
    }

    for alias in aliases:
        key = lookup.get(normalize_column_name(alias))
        if key is not None:
            return row[key]

    return None


def json_safe_record(row):
    result = {}

    for key, value in row.items():
        if value is None or (
            not isinstance(value, (list, dict)) and pd.isna(value)
        ):
            result[str(key)] = None
        elif hasattr(value, "isoformat"):
            result[str(key)] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
        else:
            result[str(key)] = str(value)

    return result


def file_checksum(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def make_batch_key(feed_type, source_file, checksum):
    return hashlib.sha256(
        f"{feed_type}|{source_file}|{checksum}".encode()
    ).hexdigest()


def preflight_inputs():
    """
    Discover available feeds.

    A run may contain one or several independent batches.
    """
    resolved = {}
    errors = []

    for country, spec in COUNTRY_FILES.items():
        path = next(
            (
                DATA_DIR / name
                for name in spec["filenames"]
                if (DATA_DIR / name).is_file()
            ),
            None,
        )

        if path is not None:
            if path.stat().st_size == 0:
                errors.append(
                    f"Profile feed is empty: {path.name}"
                )
            else:
                resolved[country] = path

    redemption_path = (
        REDEMPTION_FILE
        if REDEMPTION_FILE.is_file()
        else None
    )

    if (
        redemption_path is not None
        and redemption_path.stat().st_size == 0
    ):
        errors.append(
            f"Redemption JSON feed is empty: {redemption_path}"
        )

    if errors:
        raise ValueError(
            "Input preflight failed:\n- "
            + "\n- ".join(errors)
        )

    if not resolved and redemption_path is None:
        raise FileNotFoundError(
            "No input feeds found. Add at least one profile "
            "file or redemption JSON feed."
        )

    return resolved, redemption_path


def read_profile_file(path, file_type):
    if file_type == "excel":
        return pd.read_excel(
            path,
            sheet_name=0,
            dtype=object,
        )

    return pd.read_csv(
        path,
        dtype=object,
        keep_default_na=True,
    )


def _optional_text(value, field, max_length, warnings):
    value = clean_text(value)

    if value is not None and len(value) > max_length:
        warnings.append(
            f"{field} exceeds maximum length {max_length}; "
            "stored as NULL"
        )
        return None

    return value


def transform_source_row(row, country, filename, row_number):
    name = clean_text(
        get_column(row, "Member Name", "Name")
    )

    member_id = clean_text(
        get_column(row, "Unique ID", "Member ID", "ID")
    )

    tier = clean_text(
        get_column(row, "Tier Type", "Tier Code", "TierCode")
    )

    dob_raw = clean_text(
        get_column(row, "Date of Birth", "DOB")
    )

    enrollment_raw = clean_text(
        get_column(
            row,
            "Date of Enrollment",
            "Enrollment Date",
            "EnrollmentDate",
        )
    )

    flight_raw = clean_text(
        get_column(
            row,
            "Date of Flight",
            "Flight Date",
            "FlightDate",
            "Last Flight Date",
        )
    )

    errors = []
    warnings = []

    if not name:
        errors.append(
            "Member Name is mandatory but missing"
        )
    elif len(name) > 255:
        errors.append(
            "Member Name exceeds maximum length 255"
        )

    if not member_id:
        errors.append(
            "Member ID is mandatory but missing"
        )
    elif len(member_id) > 18:
        errors.append(
            "Member ID exceeds maximum length 18"
        )

    enrollment = normalize_date(enrollment_raw)

    if enrollment is None:
        errors.append(
            "Enrollment Date is mandatory but missing"
        )
    elif enrollment == INVALID_DATE:
        errors.append(
            f"Invalid Enrollment Date: {enrollment_raw}"
        )

    dob = normalize_date(dob_raw)
    flight = normalize_date(flight_raw)

    if dob == INVALID_DATE:
        warnings.append(
            f"Invalid optional Date of Birth '{dob_raw}'; "
            "stored as NULL"
        )
        dob = None

    if flight == INVALID_DATE:
        warnings.append(
            f"Invalid optional Flight Date '{flight_raw}'; "
            "stored as NULL"
        )
        flight = None

    tier = _optional_text(
        tier, "Tier Code", 5, warnings
    )

    agent = _optional_text(
        get_column(row, "Agent Name", "Agent_Name"),
        "Agent Name",
        255,
        warnings,
    )

    state = _optional_text(
        get_column(row, "State"),
        "State",
        5,
        warnings,
    )

    member_country = (
        clean_text(get_column(row, "Country"))
        or country
        or ""
    ).upper()

    if member_country and member_country not in COUNTRY_CODES:
        errors.append(
            f"Unsupported Country code: {member_country}"
        )

    if member_country == "AU":
        warnings.append(
            "Country code AU retained from source; "
            "routed to Australia target (AUS)"
        )

    post_raw = clean_text(
        get_column(
            row,
            "Post Code",
            "PostCode",
            "Postal Code",
        )
    )

    post_code = None

    if post_raw:
        if re.fullmatch(r"\d{1,5}", post_raw):
            post_code = int(post_raw)
        else:
            warnings.append(
                f"Invalid optional Post Code '{post_raw}'; "
                "stored as NULL (expected up to 5 digits)"
            )

    active = _optional_text(
        get_column(
            row,
            "Is Active",
            "Active Member",
            "Is_Active",
        ),
        "Active Member",
        1,
        warnings,
    )

    individual = _optional_text(
        get_column(
            row,
            "Individual or Corporate",
            "Individual_or_Corporate",
        ),
        "Individual or Corporate",
        20,
        warnings,
    )

    record = {
        "source_file": filename,
        "source_country": country,
        "source_row_number": row_number,
        "member_id": member_id,
        "member_name": name,
        "tier_code": tier,
        "dob_raw": dob_raw,
        "enrollment_date_raw": enrollment_raw,
        "flight_date_raw": flight_raw,
        "dob": dob if isinstance(dob, date) else None,
        "enrollment_date": (
            enrollment
            if isinstance(enrollment, date)
            else None
        ),
        "flight_date": (
            flight
            if isinstance(flight, date)
            else None
        ),
        "agent_name": agent,
        "state": state,
        "country": member_country or None,
        "post_code": post_code,
        "is_active": active,
        "individual_or_corporate": individual,
        "age": (
            calculate_age(dob)
            if isinstance(dob, date)
            else None
        ),
        "is_stale_member": (
            calculate_stale_member(flight)
            if isinstance(flight, date)
            else None
        ),
    }

    return record, errors, warnings


def extract_member_records(path, country):
    frame = read_profile_file(
        path,
        COUNTRY_FILES[country]["type"],
    )

    if frame.empty:
        raise ValueError(
            f"Profile feed has headers but no data rows: "
            f"{path.name}"
        )

    raw = []
    accepted = []
    rejected = []
    warnings = []

    for row_number, (_, row) in enumerate(
        frame.iterrows(),
        1,
    ):
        original = json_safe_record(row.to_dict())

        raw.append({
            "source_file": path.name,
            "source_country": country,
            "source_row_number": row_number,
            "raw_record": original,
        })

        record, errors, row_warnings = transform_source_row(
            row,
            country,
            path.name,
            row_number,
        )

        for warning in row_warnings:
            warnings.append({
                "source_file": path.name,
                "source_country": country,
                "source_row_number": row_number,
                "issue_type": "WARNING",
                "issue_detail": warning,
            })

        if errors:
            rejected.append({
                "source_file": path.name,
                "source_country": country,
                "source_row_number": row_number,
                "raw_record": original,
                "rejection_reason": "; ".join(errors),
            })
        else:
            accepted.append(record)

    return raw, accepted, rejected, warnings


def load_json_feeds(path):
    with Path(path).open(encoding="utf-8") as f:
        payload = json.load(f)

    feeds = payload if isinstance(payload, list) else [payload]

    if not feeds or any(
        not isinstance(feed, dict)
        for feed in feeds
    ):
        raise ValueError(
            "Redemption JSON must be an object or a "
            "non-empty array of feed objects"
        )

    return feeds


def validate_and_flatten_redemptions(
    feeds,
    source_file=None,
):
    flattened = []
    issues = []

    source_file = source_file or REDEMPTION_FILE.name

    for feed_no, feed in enumerate(feeds, 1):
        member_id = clean_text(feed.get("member_id"))
        feed_date = normalize_date(feed.get("feed_date"))

        errors = []

        if not member_id:
            errors.append("member_id is mandatory")
        elif len(member_id) > 18:
            errors.append(
                "member_id exceeds maximum length 18"
            )

        if not isinstance(feed_date, date):
            errors.append(
                "feed_date is missing or invalid"
            )

        items = feed.get("redemptions")

        if not isinstance(items, list):
            errors.append(
                "redemptions must be an array"
            )
            items = []

        if errors:
            issues.append({
                "source_file": source_file,
                "source_row_number": feed_no,
                "issue_type": "REJECTED_FEED",
                "issue_detail": "; ".join(errors),
            })
            continue

        for item_no, item in enumerate(items, 1):
            errors = []

            if not isinstance(item, dict):
                errors.append(
                    "redemption item must be an object"
                )
                item = {}

            txn_id = clean_text(item.get("txn_id"))
            txn_date = normalize_date(
                item.get("txn_date")
            )

            partner = clean_text(item.get("partner"))
            status = clean_text(item.get("status"))
            miles = item.get("miles_redeemed")

            if not txn_id:
                errors.append("txn_id is mandatory")
            elif len(txn_id) > 50:
                errors.append(
                    "txn_id exceeds maximum length 50"
                )

            if not isinstance(txn_date, date):
                errors.append(
                    "txn_date is missing or invalid"
                )

            if not partner:
                errors.append("partner is mandatory")
            elif len(partner) > 100:
                errors.append(
                    "partner exceeds maximum length 100"
                )

            if (
                isinstance(miles, bool)
                or not isinstance(miles, int)
                or miles < 0
            ):
                errors.append(
                    "miles_redeemed must be a "
                    "non-negative integer"
                )

            if not status:
                errors.append("status is mandatory")
            elif len(status) > 30:
                errors.append(
                    "status exceeds maximum length 30"
                )

            if errors:
                issues.append({
                    "source_file": source_file,
                    "source_row_number": feed_no,
                    "issue_type": "REJECTED_REDEMPTION",
                    "issue_detail": (
                        f"feed {feed_no}, redemption "
                        f"{item_no}: " + "; ".join(errors)
                    ),
                })
            else:
                flattened.append({
                    "txn_id": txn_id,
                    "member_id": member_id,
                    "txn_date": txn_date,
                    "partner": partner,
                    "miles_redeemed": miles,
                    "status": status,
                    "feed_date": feed_date,
                })

    return flattened, issues


def register_batch(
    engine,
    feed_type,
    source_file,
    checksum,
):
    key = make_batch_key(
        feed_type,
        source_file,
        checksum,
    )

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO skypoints.ingestion_batches
                    (batch_key, feed_type, source_file,
                     checksum, status)
                VALUES
                    (:key, :feed, :file, :checksum, 'RECEIVED')
                ON CONFLICT (batch_key) DO NOTHING
            """),
            {
                "key": key,
                "feed": feed_type,
                "file": source_file,
                "checksum": checksum,
            },
        )

        batch = conn.execute(
            text("""
                SELECT batch_id, status
                FROM skypoints.ingestion_batches
                WHERE batch_key = :key
                FOR UPDATE
            """),
            {"key": key},
        ).mappings().one()

        if batch["status"] == "SUCCEEDED":
            return None

        if batch["status"] == "PROCESSING":
            raise RuntimeError(
                f"Batch {batch['batch_id']} is already PROCESSING"
            )

        conn.execute(
            text("""
                UPDATE skypoints.ingestion_batches
                SET status = 'PROCESSING',
                    started_at = CURRENT_TIMESTAMP,
                    completed_at = NULL,
                    error_message = NULL
                WHERE batch_id = :id
            """),
            {"id": batch["batch_id"]},
        )

        return batch["batch_id"]


def mark_batch_failed(engine, batch_id, error):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE skypoints.ingestion_batches
                SET status = 'FAILED',
                    completed_at = CURRENT_TIMESTAMP,
                    error_message = :error
                WHERE batch_id = :id
            """),
            {
                "id": batch_id,
                "error": str(error)[:4000],
            },
        )


def persist_profile_batch(
    conn,
    batch_id,
    raw,
    accepted,
    rejected,
    warnings,
):
    for collection in (
        raw,
        accepted,
        rejected,
        warnings,
    ):
        for row in collection:
            row["ingestion_batch_id"] = batch_id

    if raw:
        conn.execute(
            text("""
                INSERT INTO skypoints.raw_member_profiles
                    (ingestion_batch_id, source_file,
                     source_country, source_row_number,
                     raw_record)
                VALUES
                    (:ingestion_batch_id, :source_file,
                     :source_country, :source_row_number,
                     CAST(:raw_record AS JSONB))
            """),
            [
                dict(
                    row,
                    raw_record=json.dumps(row["raw_record"]),
                )
                for row in raw
            ],
        )

    if rejected:
        conn.execute(
            text("""
                INSERT INTO skypoints.removed_records
                    (ingestion_batch_id, source_file,
                     source_country, source_row_number,
                     raw_record, rejection_reason)
                VALUES
                    (:ingestion_batch_id, :source_file,
                     :source_country, :source_row_number,
                     CAST(:raw_record AS JSONB),
                     :rejection_reason)
            """),
            [
                dict(
                    row,
                    raw_record=json.dumps(row["raw_record"]),
                )
                for row in rejected
            ],
        )

    if warnings:
        conn.execute(
            text("""
                INSERT INTO skypoints.data_quality_issues
                    (ingestion_batch_id, source_file,
                     source_country, source_row_number,
                     issue_type, issue_detail)
                VALUES
                    (:ingestion_batch_id, :source_file,
                     :source_country, :source_row_number,
                     :issue_type, :issue_detail)
            """),
            warnings,
        )

    if accepted:
        pd.DataFrame(accepted).to_sql(
            "stg_member_profiles",
            conn,
            schema="skypoints",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000,
        )


def publish_profile_batch(conn, records):
    """
    Upsert only this batch's winners.
    Never truncate previously published profiles.
    """
    latest = {}

    for row in records:
        country = (
            row["country"]
            or row["source_country"]
            or ""
        ).strip().upper()

        table = TARGET_TABLES.get(country)

        if not table:
            raise ValueError(
                f"No target table configured for country "
                f"{country!r}"
            )

        key = (
            table,
            row["member_name"].strip().casefold(),
        )

        rank = (
            row["enrollment_date"],
            row["flight_date"] or date.min,
            row["source_row_number"],
        )

        if (
            key not in latest
            or rank >= latest[key][0]
        ):
            latest[key] = (rank, row)

    cols = (
        "member_name",
        "member_id",
        "tier_code",
        "enrollment_date",
        "flight_date",
        "dob",
        "agent_name",
        "state",
        "country",
        "post_code",
        "is_active",
        "individual_or_corporate",
        "age",
        "is_stale_member",
        "source_file",
    )

    assignments = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in cols
        if column != "member_name"
    )

    assignments += ", updated_at=CURRENT_TIMESTAMP"

    count = 0

    for (table, _), (_, row) in latest.items():
        statement = f"""
            INSERT INTO skypoints.{table}
                ({', '.join(cols)})
            VALUES
                ({', '.join(':' + column for column in cols)})
            ON CONFLICT ((LOWER(BTRIM(member_name))))
            DO UPDATE SET {assignments}
            WHERE EXCLUDED.enrollment_date
                >= skypoints.{table}.enrollment_date
        """

        conn.execute(
            text(statement),
            {
                column: row[column]
                for column in cols
            },
        )

        count += 1

    return count


def process_profile_file(engine, country, path):
    batch_id = register_batch(
        engine,
        f"PROFILE_{country}",
        path.name,
        file_checksum(path),
    )

    if batch_id is None:
        logging.info(
            "Skipping successful replay: %s",
            path.name,
        )
        return

    try:
        raw, accepted, rejected, warnings = (
            extract_member_records(path, country)
        )

        with engine.begin() as conn:
            persist_profile_batch(
                conn,
                batch_id,
                raw,
                accepted,
                rejected,
                warnings,
            )

            publish_profile_batch(conn, accepted)

            conn.execute(
                text("""
                    UPDATE skypoints.ingestion_batches
                    SET status = 'SUCCEEDED',
                        completed_at = CURRENT_TIMESTAMP,
                        total_records = :total,
                        processed_records = :processed,
                        rejected_records = :rejected
                    WHERE batch_id = :id
                """),
                {
                    "id": batch_id,
                    "total": len(raw),
                    "processed": len(accepted),
                    "rejected": len(rejected),
                },
            )

        logging.info(
            "Profile batch %s succeeded: "
            "accepted=%d rejected=%d",
            batch_id,
            len(accepted),
            len(rejected),
        )

    except Exception as exc:
        mark_batch_failed(engine, batch_id, exc)
        raise


def persist_redemption_batch(
    conn,
    batch_id,
    path,
    feeds,
    rows,
    issues,
):
    """
    Persist raw feeds and transactions.

    Return the number of conflicting transaction IDs.
    """
    for feed in feeds:
        payload = json.dumps(feed, sort_keys=True)

        conn.execute(
            text("""
                INSERT INTO skypoints.raw_redemptions_json
                    (ingestion_batch_id, source_file,
                     payload, payload_hash)
                VALUES
                    (:batch, :file,
                     CAST(:payload AS JSONB), :hash)
                ON CONFLICT
                    (ingestion_batch_id, payload_hash)
                DO NOTHING
            """),
            {
                "batch": batch_id,
                "file": path.name,
                "payload": payload,
                "hash": hashlib.sha256(
                    payload.encode()
                ).hexdigest(),
            },
        )

    conflicting_transactions = 0

    for row in rows:
        result = conn.execute(
            text("""
                INSERT INTO skypoints.fact_redemptions
                    (ingestion_batch_id, txn_id, member_id,
                     txn_date, partner, miles_redeemed,
                     status, feed_date)
                VALUES
                    (:batch_id, :txn_id, :member_id,
                     :txn_date, :partner, :miles_redeemed,
                     :status, :feed_date)
                ON CONFLICT (txn_id) DO NOTHING
                RETURNING txn_id
            """),
            dict(row, batch_id=batch_id),
        )

        # No RETURNING value means this transaction ID
        # already exists.
        if result.scalar_one_or_none() is not None:
            continue

        existing = conn.execute(
            text("""
                SELECT member_id, txn_date, partner,
                       miles_redeemed, status, feed_date
                FROM skypoints.fact_redemptions
                WHERE txn_id = :txn_id
            """),
            {"txn_id": row["txn_id"]},
        ).mappings().first()

        if existing is None:
            raise RuntimeError(
                f"Transaction {row['txn_id']} conflicted "
                "during insert but could not be read back"
            )

        compared_fields = (
            "member_id",
            "txn_date",
            "partner",
            "miles_redeemed",
            "status",
            "feed_date",
        )

        if any(
            existing[field] != row[field]
            for field in compared_fields
        ):
            conflicting_transactions += 1

            issues.append({
                "source_file": path.name,
                "source_row_number": None,
                "issue_type": "CONFLICTING_DUPLICATE_TXN",
                "issue_detail": (
                    f"txn_id {row['txn_id']} already exists "
                    "with different values"
                ),
            })

    if issues:
        conn.execute(
            text("""
                INSERT INTO skypoints.redemption_issues
                    (ingestion_batch_id, source_file,
                     source_row_number, issue_type,
                     issue_detail)
                VALUES
                    (:ingestion_batch_id, :source_file,
                     :source_row_number, :issue_type,
                     :issue_detail)
            """),
            [
                dict(
                    issue,
                    ingestion_batch_id=batch_id,
                )
                for issue in issues
            ],
        )

    return conflicting_transactions


def redemption_batch_counts(
    valid_transactions,
    issues,
    conflicting_transactions=0,
):
    """
    Return consistent batch counts.

    Exact existing replays count as processed.
    """
    processed = (
        len(valid_transactions)
        - conflicting_transactions
    )

    rejected = len(issues)
    total = processed + rejected

    return total, processed, rejected


def process_redemption_file(engine, path):
    batch_id = register_batch(
        engine,
        "REDEMPTION",
        path.name,
        file_checksum(path),
    )

    if batch_id is None:
        logging.info(
            "Skipping successful redemption replay: %s",
            path.name,
        )
        return

    try:
        feeds = load_json_feeds(path)

        rows, issues = validate_and_flatten_redemptions(
            feeds,
            path.name,
        )

        with engine.begin() as conn:
            conflicting = persist_redemption_batch(
                conn,
                batch_id,
                path,
                feeds,
                rows,
                issues,
            )

            total, processed, rejected = (
                redemption_batch_counts(
                    rows,
                    issues,
                    conflicting,
                )
            )

            conn.execute(
                text("""
                    UPDATE skypoints.ingestion_batches
                    SET status = 'SUCCEEDED',
                        completed_at = CURRENT_TIMESTAMP,
                        total_records = :total,
                        processed_records = :processed,
                        rejected_records = :rejected
                    WHERE batch_id = :id
                """),
                {
                    "id": batch_id,
                    "total": total,
                    "processed": processed,
                    "rejected": rejected,
                },
            )

        logging.info(
            "Redemption batch %s succeeded: "
            "processed=%d rejected=%d",
            batch_id,
            processed,
            rejected,
        )

    except Exception as exc:
        mark_batch_failed(engine, batch_id, exc)
        raise


def main():
    logging.info("Starting SkyPoints batch pipeline")

    resolved, redemption_path = preflight_inputs()
    engine = get_engine()

    try:
        for country, path in resolved.items():
            process_profile_file(
                engine,
                country,
                path,
            )

        if redemption_path is not None:
            process_redemption_file(
                engine,
                redemption_path,
            )

        logging.info("Pipeline completed")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
