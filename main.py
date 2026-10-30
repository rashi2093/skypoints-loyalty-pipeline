
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


# ---------------------------------------------------------
# LOGGING AND DATABASE CONFIGURATION
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DB_USER = os.getenv("USER", "postgres")

DB_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg2://{DB_USER}@localhost:5432/skypoints_db",
)

engine = create_engine(DB_URL, pool_pre_ping=True)


# ---------------------------------------------------------
# SOURCE FILES AND TARGET TABLES
# ---------------------------------------------------------

COUNTRY_FILES = {
    "USA": (("USA(in).csv", "USA.csv"), "csv"),
    "IND": (("IND(in).csv", "IND.csv"), "csv"),
    "AUS": (("AUS.xlsx",), "excel"),
}

TARGET_TABLES = {
    "USA": "table_usa",
    "IND": "table_ind",
    "AUS": "table_aus",
    "PHIL": "table_phil",
    "CAN": "table_can",
}


# ---------------------------------------------------------
# GENERAL DATA CLEANING UTILITIES
# ---------------------------------------------------------

def clean_text(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    result = str(value).strip()

    return result if result else None


def normalize_column_name(value):
    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).strip().lower(),
    )


def get_column(row, *aliases):
    """Find a source column using case/punctuation-insensitive aliases."""

    lookup = {
        normalize_column_name(k): k
        for k in row.index
    }

    for alias in aliases:
        actual = lookup.get(normalize_column_name(alias))

        if actual is not None:
            return row[actual]

    return None


def json_safe_record(row):
    """Convert source values into JSON-serializable values."""

    result = {}

    for key, value in row.items():

        if value is None or pd.isna(value):
            result[str(key)] = None

        elif hasattr(value, "isoformat"):
            result[str(key)] = value.isoformat()

        else:
            result[str(key)] = (
                str(value)
                if not isinstance(value, (str, int, float, bool))
                else value
            )

    return result


# ---------------------------------------------------------
# EXTRACT SOURCE FILES
# ---------------------------------------------------------

def load_source_file(country, filenames, file_type):

    path = next(
        (
            DATA_DIR / name
            for name in filenames
            if (DATA_DIR / name).exists()
        ),
        None,
    )

    if path is None:

        logging.warning(
            "No input file found for %s. Tried: %s",
            country,
            ", ".join(filenames),
        )

        return None

    logging.info(
        "Reading %s feed from %s",
        country,
        path.name,
    )

    if file_type == "excel":
        return pd.read_excel(path, sheet_name=0)

    return pd.read_csv(path, dtype=object)


# ---------------------------------------------------------
# TRANSFORM AND VALIDATE MEMBER RECORDS
# ---------------------------------------------------------

def transform_source_row(row, country, filename, row_number):
    """
    Convert one source row into the common staging structure.

    Source filename country is used as the country routing hint
    because the shared sample does not contain a Country column.
    """

    member_name = clean_text(
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

    dob = normalize_date(dob_raw)
    enrollment_date = normalize_date(enrollment_raw)
    flight_date = normalize_date(flight_raw)

    reasons = []

    # Mandatory field validation
    if not member_name:
        reasons.append(
            "Member Name is mandatory but missing"
        )

    if not member_id:
        reasons.append(
            "Member ID is mandatory but missing"
        )

    if enrollment_date is None:
        reasons.append(
            "Enrollment Date is mandatory but missing"
        )

    elif enrollment_date == INVALID_DATE:
        reasons.append(
            f"Invalid Enrollment Date: {enrollment_raw}"
        )

    # Optional dates: reject only if populated but invalid
    if dob == INVALID_DATE:
        reasons.append(
            f"Invalid Date of Birth: {dob_raw}"
        )

    if flight_date == INVALID_DATE:
        reasons.append(
            f"Invalid Flight Date: {flight_raw}"
        )

    individual_or_corporate = clean_text(
        get_column(
            row,
            "Individual or Corporate",
            "Individual_or_Corporate",
        )
    ) or "I"

    # Country in source takes precedence.
    # Otherwise, use the source file country.
    member_country = (
        clean_text(get_column(row, "Country"))
        or country
    )

    post_code_value = clean_text(
        get_column(
            row,
            "Post Code",
            "PostCode",
            "Postal Code",
        )
    )

    post_code = None

    if post_code_value:

        try:
            post_code = int(float(post_code_value))

        except (TypeError, ValueError):
            reasons.append(
                f"Invalid Post Code: {post_code_value}"
            )

    record = {
        "source_file": filename,
        "source_country": country,
        "source_row_number": row_number,

        "member_id": member_id,
        "member_name": member_name,
        "tier_code": tier,

        "dob_raw": dob_raw,
        "enrollment_date_raw": enrollment_raw,
        "flight_date_raw": flight_raw,

        "dob": (
            None
            if dob in (None, INVALID_DATE)
            else dob
        ),

        "enrollment_date": (
            None
            if enrollment_date in (None, INVALID_DATE)
            else enrollment_date
        ),

        "flight_date": (
            None
            if flight_date in (None, INVALID_DATE)
            else flight_date
        ),

        "agent_name": clean_text(
            get_column(row, "Agent Name", "Agent_Name")
        ),

        "state": clean_text(
            get_column(row, "State")
        ),

        "country": member_country,
        "post_code": post_code,

        "is_active": clean_text(
            get_column(
                row,
                "Is Active",
                "Active Member",
                "Is_Active",
            )
        ),

        "individual_or_corporate": individual_or_corporate,

        "age": (
            calculate_age(dob)
            if isinstance(dob, date)
            else None
        ),

        "is_stale_member": calculate_stale_member(
            flight_date
        ),

        "validation_status": (
            "REJECTED"
            if reasons
            else "VALID"
        ),
    }

    return record, reasons


def extract_all_member_records():

    valid_records = []
    rejected_records = []
    raw_records = []

    for country, (filenames, file_type) in COUNTRY_FILES.items():

        df = load_source_file(
            country,
            filenames,
            file_type,
        )

        if df is None:
            continue

        filename = next(
            name
            for name in filenames
            if (DATA_DIR / name).exists()
        )

        for row_number, (_, row) in enumerate(
            df.iterrows(),
            start=1,
        ):

            raw_record = json_safe_record(
                row.to_dict()
            )

            raw_records.append({
                "source_file": filename,
                "source_country": country,
                "source_row_number": row_number,
                "raw_record": raw_record,
            })

            transformed, reasons = transform_source_row(
                row,
                country,
                filename,
                row_number,
            )

            if reasons:

                rejected_records.append({
                    "source_file": filename,
                    "source_country": country,
                    "source_row_number": row_number,
                    "raw_record": raw_record,
                    "rejection_reason": "; ".join(reasons),
                })

            else:
                valid_records.append(transformed)

    return (
        raw_records,
        valid_records,
        rejected_records,
    )


# ---------------------------------------------------------
# LOAD RAW MEMBER AND REJECTED RECORDS
# ---------------------------------------------------------

def load_raw_and_validation_records(
    conn,
    raw_records,
    rejected_records,
):

    for item in raw_records:

        conn.execute(
            text("""
                INSERT INTO skypoints.raw_member_profiles
                    (
                        source_file,
                        source_country,
                        source_row_number,
                        raw_record
                    )
                VALUES
                    (
                        :source_file,
                        :source_country,
                        :source_row_number,
                        CAST(:raw_record AS JSONB)
                    )
            """),
            {
                "source_file": item["source_file"],
                "source_country": item["source_country"],
                "source_row_number": item["source_row_number"],
                "raw_record": json.dumps(
                    item["raw_record"]
                ),
            },
        )

    for item in rejected_records:

        conn.execute(
            text("""
                INSERT INTO skypoints.removed_records
                    (
                        source_file,
                        source_country,
                        source_row_number,
                        raw_record,
                        rejection_reason
                    )
                VALUES
                    (
                        :source_file,
                        :source_country,
                        :source_row_number,
                        CAST(:raw_record AS JSONB),
                        :rejection_reason
                    )
            """),
            {
                "source_file": item["source_file"],
                "source_country": item["source_country"],
                "source_row_number": item["source_row_number"],
                "raw_record": json.dumps(
                    item["raw_record"]
                ),
                "rejection_reason": item["rejection_reason"],
            },
        )


# ---------------------------------------------------------
# LOAD STAGING TABLE
# ---------------------------------------------------------

def load_staging(conn, valid_records):

    if not valid_records:

        logging.warning(
            "No valid member rows found; staging remains empty."
        )

        return

    df = pd.DataFrame(valid_records)

    df.to_sql(
        "stg_member_profiles",
        conn,
        schema="skypoints",
        if_exists="append",
        index=False,
        method="multi",
    )


# ---------------------------------------------------------
# LOAD SEMI-STRUCTURED JSON REDEMPTION FEED
# ---------------------------------------------------------

def insert_json_redemptions(conn):
    """
    Persist the assessment sample JSON and flatten
    its redemption array into the fact table.
    """

    payload = {
        "member_id": "223457",
        "feed_date": "20240115",

        "redemptions": [
            {
                "txn_id": "RX10091",
                "txn_date": "20240110",
                "partner": "AeroLink",
                "miles_redeemed": 12000,
                "status": "COMPLETED",
            },
            {
                "txn_id": "RX10092",
                "txn_date": "20240113",
                "partner": "SkyPoints",
                "miles_redeemed": 5000,
                "status": "PENDING",
            },
        ],
    }

    conn.execute(
        text("""
            INSERT INTO skypoints.raw_redemptions_json
                (payload)
            VALUES
                (CAST(:payload AS JSONB))
        """),
        {
            "payload": json.dumps(payload)
        },
    )

    feed_date = normalize_date(
        payload.get("feed_date")
    )

    for redemption in payload.get("redemptions", []):

        txn_date = normalize_date(
            redemption.get("txn_date")
        )

        if (
            not redemption.get("txn_id")
            or not isinstance(txn_date, date)
        ):

            logging.warning(
                "Skipping invalid redemption record: %s",
                redemption,
            )

            continue

        conn.execute(
            text("""
                INSERT INTO skypoints.fact_redemptions
                    (
                        txn_id,
                        member_id,
                        txn_date,
                        partner,
                        miles_redeemed,
                        status,
                        feed_date
                    )
                VALUES
                    (
                        :txn_id,
                        :member_id,
                        :txn_date,
                        :partner,
                        :miles_redeemed,
                        :status,
                        :feed_date
                    )
                ON CONFLICT (txn_id) DO NOTHING
            """),
            {
                "txn_id": redemption["txn_id"],
                "member_id": payload["member_id"],
                "txn_date": txn_date,
                "partner": redemption.get("partner"),
                "miles_redeemed": redemption.get(
                    "miles_redeemed"
                ),
                "status": redemption.get("status"),
                "feed_date": feed_date,
            },
        )


# ---------------------------------------------------------
# ROUTE LATEST MEMBER RECORD TO COUNTRY TABLES
# ---------------------------------------------------------

def route_members_latest_wins(conn):
    """
    Latest available record wins per member_id.

    The source feeds do not provide a source-update timestamp.
    Therefore, flight_date and enrollment_date are used as
    deterministic proxies.

    Tied rows are resolved by highest staging_id.
    """

    ranked_sql = """
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY member_id
                    ORDER BY
                        flight_date DESC NULLS LAST,
                        enrollment_date DESC NULLS LAST,
                        staging_id DESC
                ) AS rn
            FROM skypoints.stg_member_profiles
        )

        SELECT *
        FROM ranked
        WHERE rn = 1
    """

    winners = conn.execute(
        text(ranked_sql)
    ).mappings().all()

    # Clear all target tables before loading winners.
    for table_name in TARGET_TABLES.values():

        conn.execute(
            text(
                f"TRUNCATE TABLE skypoints.{table_name}"
            )
        )

    insert_sql_template = """
        INSERT INTO skypoints.{table_name} (
            member_id,
            member_name,
            tier_code,
            enrollment_date,
            flight_date,
            dob,
            agent_name,
            state,
            country,
            post_code,
            is_active,
            individual_or_corporate,
            age,
            is_stale_member,
            source_file
        )
        VALUES (
            :member_id,
            :member_name,
            :tier_code,
            :enrollment_date,
            :flight_date,
            :dob,
            :agent_name,
            :state,
            :country,
            :post_code,
            :is_active,
            :individual_or_corporate,
            :age,
            :is_stale_member,
            :source_file
        )
    """

    for member in winners:

        country = (
            member["country"]
            or member["source_country"]
            or ""
        ).upper()

        table_name = TARGET_TABLES.get(country)

        if table_name is None:

            logging.warning(
                "No target table configured for country '%s'; "
                "member_id=%s not routed.",
                country,
                member["member_id"],
            )

            continue

        conn.execute(
            text(
                insert_sql_template.format(
                    table_name=table_name
                )
            ),
            {
                key: member[key]
                for key in (
                    "member_id",
                    "member_name",
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
            },
        )


# ---------------------------------------------------------
# MAIN PIPELINE EXECUTION
# ---------------------------------------------------------

def main():

    logging.info(
        "Starting SkyPoints pipeline"
    )

    raw_records, valid_records, rejected_records = (
        extract_all_member_records()
    )

    logging.info(
        "Extracted %d raw rows; %d valid; %d rejected.",
        len(raw_records),
        len(valid_records),
        len(rejected_records),
    )

    # All database operations run in one transaction.
    with engine.begin() as conn:

        # Full-refresh cleanup.
        # This prevents duplicate raw and redemption records
        # when the pipeline is executed repeatedly.
        conn.execute(
            text("""
                TRUNCATE TABLE
                    skypoints.raw_member_profiles,
                    skypoints.removed_records,
                    skypoints.raw_redemptions_json,
                    skypoints.fact_redemptions,
                    skypoints.stg_member_profiles
                RESTART IDENTITY;
            """)
        )

        # Load raw records and validation failures.
        load_raw_and_validation_records(
            conn,
            raw_records,
            rejected_records,
        )

        # Load validated member records into staging.
        load_staging(
            conn,
            valid_records,
        )

        # Persist and flatten the JSON redemption feed.
        insert_json_redemptions(conn)

        # Route latest member records to country tables.
        route_members_latest_wins(conn)

    logging.info(
        "SkyPoints pipeline completed successfully."
    )


if __name__ == "__main__":
    main()
