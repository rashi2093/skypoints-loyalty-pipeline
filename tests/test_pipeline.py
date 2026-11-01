
from datetime import date
import hashlib

import pandas as pd

from main import (
    make_batch_key,
    transform_source_row,
    validate_and_flatten_redemptions,
    persist_redemption_batch,
    redemption_batch_counts,
)

from src.utils import (
    INVALID_DATE,
    calculate_age,
    calculate_stale_member,
    normalize_date,
)


def test_assessment_yyyymmdd():
    assert normalize_date("20240115") == date(2024, 1, 15)


def test_usa_numeric_dates():
    assert normalize_date("6152022") == date(2022, 6, 15)
    assert normalize_date(1052022) == date(2022, 1, 5)
    assert normalize_date(12282021) == date(2021, 12, 28)


def test_iso_and_slash_dates():
    assert normalize_date("2022-05-11") == date(2022, 5, 11)
    assert normalize_date("12/1/1998") == date(1998, 12, 1)
    assert normalize_date("3/5/2022") == date(2022, 3, 5)


def test_invalid_and_missing_dates():
    assert normalize_date("2021-13-13") == INVALID_DATE
    assert normalize_date("20241315") == INVALID_DATE
    assert normalize_date(None) is None
    assert normalize_date("") is None


def test_age_calculation():
    ref = date(2026, 10, 30)
    assert calculate_age(date(2000, 10, 30), ref) == 26
    assert calculate_age(date(2000, 11, 1), ref) == 25
    assert calculate_age(None, ref) is None


def test_stale_member_threshold():
    ref = date(2026, 10, 30)
    assert calculate_stale_member(date(2026, 7, 31), ref) == "Y"
    assert calculate_stale_member(date(2026, 8, 1), ref) == "N"
    assert calculate_stale_member(ref, ref) == "N"
    assert calculate_stale_member(None, ref) is None


def test_missing_optional_fields_do_not_reject_member():
    row = pd.Series({
        "ID": "1",
        "Name": "Sam",
        "EnrollmentDate": "6152022",
    })

    record, errors, _ = transform_source_row(
        row, "USA", "USA.csv", 1
    )

    assert errors == []
    assert record["dob"] is None
    assert record["age"] is None
    assert record["flight_date"] is None


def test_invalid_optional_date_is_warning():
    row = pd.Series({
        "ID": "1",
        "Name": "Sam",
        "EnrollmentDate": "6152022",
        "DOB": "2021-13-13",
    })

    record, errors, warnings = transform_source_row(
        row, "USA", "USA.csv", 1
    )

    assert errors == []
    assert record["dob"] is None
    assert any(
        "Invalid optional Date of Birth" in warning
        for warning in warnings
    )


def test_mandatory_invalid_enrollment_rejected():
    row = pd.Series({
        "ID": "1",
        "Name": "Sam",
        "EnrollmentDate": "2021-13-13",
    })

    _, errors, _ = transform_source_row(
        row, "USA", "USA.csv", 1
    )

    assert any(
        "Invalid Enrollment Date" in error
        for error in errors
    )


def test_field_length_validation():
    row = pd.Series({
        "ID": "1234567890123456789",
        "Name": "Sam",
        "EnrollmentDate": "20240101",
    })

    _, errors, _ = transform_source_row(
        row, "USA", "USA.csv", 1
    )

    assert any(
        "Member ID exceeds maximum length 18" in error
        for error in errors
    )


def test_json_flattening_multiple_transactions():
    feeds = [{
        "member_id": "123",
        "feed_date": "20240115",
        "redemptions": [
            {
                "txn_id": "T1",
                "txn_date": "20240110",
                "partner": "P1",
                "miles_redeemed": 5,
                "status": "COMPLETED",
            },
            {
                "txn_id": "T2",
                "txn_date": "20240111",
                "partner": "P2",
                "miles_redeemed": 0,
                "status": "PENDING",
            },
        ],
    }]

    rows, issues = validate_and_flatten_redemptions(
        feeds, "daily.json"
    )

    assert len(rows) == 2
    assert issues == []
    assert rows[0]["txn_id"] == "T1"


def test_bad_redemption_rejected_but_valid_one_kept():
    feeds = [{
        "member_id": "123",
        "feed_date": "20240115",
        "redemptions": [
            {
                "txn_id": "T1",
                "txn_date": "20240110",
                "partner": "P1",
                "miles_redeemed": 5,
                "status": "COMPLETED",
            },
            {
                "txn_id": "T2",
                "txn_date": "20240111",
                "partner": "P2",
                "miles_redeemed": -1,
                "status": "PENDING",
            },
        ],
    }]

    rows, issues = validate_and_flatten_redemptions(feeds)

    assert len(rows) == 1
    assert len(issues) == 1
    assert "non-negative integer" in issues[0]["issue_detail"]


def test_missing_redemptions_array_is_reported():
    rows, issues = validate_and_flatten_redemptions([
        {
            "member_id": "123",
            "feed_date": "20240115",
        }
    ])

    assert rows == []
    assert any(
        "redemptions must be an array" in issue["issue_detail"]
        for issue in issues
    )


def test_batch_key_is_deterministic_and_content_sensitive():
    first = hashlib.sha256(b"first").hexdigest()
    second = hashlib.sha256(b"second").hexdigest()

    assert make_batch_key(
        "PROFILE_USA", "USA.csv", first
    ) == make_batch_key(
        "PROFILE_USA", "USA.csv", first
    )

    assert make_batch_key(
        "PROFILE_USA", "USA.csv", first
    ) != make_batch_key(
        "PROFILE_USA", "USA.csv", second
    )


def test_batch_key_separates_feed_and_filename():
    checksum = hashlib.sha256(b"same").hexdigest()

    assert make_batch_key(
        "PROFILE_USA", "USA.csv", checksum
    ) != make_batch_key(
        "REDEMPTION", "USA.csv", checksum
    )

    assert make_batch_key(
        "PROFILE_USA", "USA.csv", checksum
    ) != make_batch_key(
        "PROFILE_USA", "renamed.csv", checksum
    )


class _FakeResult:
    def __init__(self, scalar=None, mapping=None):
        self._scalar = scalar
        self._mapping = mapping

    def scalar_one_or_none(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping



class _FakeConnection:
    def __init__(self, existing_transaction=None):
        self.calls = []
        self.existing_transaction = existing_transaction

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params))

        if "INSERT INTO skypoints.fact_redemptions" in sql:
            return _FakeResult(
                None if self.existing_transaction is not None
                else "T1"
            )

        if (
            "SELECT member_id, txn_date, partner," in sql
            and "FROM skypoints.fact_redemptions" in sql
        ):
            return _FakeResult(
                mapping=self.existing_transaction
            )

        return _FakeResult()


def _valid_redemption_fixture():
    feeds = [{
        "member_id": "123",
        "feed_date": "20240115",
        "redemptions": [{
            "txn_id": "T1",
            "txn_date": "20240110",
            "partner": "P1",
            "miles_redeemed": 5,
            "status": "COMPLETED",
        }],
    }]

    rows, issues = validate_and_flatten_redemptions(
        feeds, "daily.json"
    )

    return feeds, rows, issues


def test_new_redemption_insert_uses_batch_id_parameter():
    from pathlib import Path

    feeds, rows, issues = _valid_redemption_fixture()
    conn = _FakeConnection()

    conflicts = persist_redemption_batch(
        conn,
        42,
        Path("daily.json"),
        feeds,
        rows,
        issues,
    )

    raw_call = next(
        call for call in conn.calls
        if "INSERT INTO skypoints.raw_redemptions_json" in call[0]
    )

    fact_call = next(
        call for call in conn.calls
        if "INSERT INTO skypoints.fact_redemptions" in call[0]
    )

    assert raw_call[1]["batch"] == 42
    assert ":batch_id" in fact_call[0]
    assert fact_call[1]["batch_id"] == 42
    assert "ingestion_batch_id" not in fact_call[1]
    assert conflicts == 0
    assert issues == []


def test_identical_existing_redemption_is_not_reported_as_conflict():
    from pathlib import Path

    feeds, rows, issues = _valid_redemption_fixture()

    existing = {
        "member_id": "123",
        "txn_date": rows[0]["txn_date"],
        "partner": "P1",
        "miles_redeemed": 5,
        "status": "COMPLETED",
        "feed_date": rows[0]["feed_date"],
    }

    conn = _FakeConnection(
        existing_transaction=existing
    )

    conflicts = persist_redemption_batch(
        conn,
        42,
        Path("daily.json"),
        feeds,
        rows,
        issues,
    )

    assert conflicts == 0
    assert issues == []


def test_redemption_batch_counts_use_consistent_record_units():
    total, processed, rejected = redemption_batch_counts(
        valid_transactions=[{}, {}, {}],
        issues=[{"issue_type": "REJECTED_REDEMPTION"}],
        conflicting_transactions=1,
    )

    assert (total, processed, rejected) == (3, 2, 1)


def test_conflicting_redemption_id_is_rejected_and_audited():
    from pathlib import Path

    feeds, rows, issues = _valid_redemption_fixture()

    existing = {
        "member_id": "999",
        "txn_date": rows[0]["txn_date"],
        "partner": "P1",
        "miles_redeemed": 5,
        "status": "COMPLETED",
        "feed_date": rows[0]["feed_date"],
    }

    conn = _FakeConnection(
        existing_transaction=existing
    )

    conflicts = persist_redemption_batch(
        conn,
        42,
        Path("daily.json"),
        feeds,
        rows,
        issues,
    )

    issue_call = next(
        call for call in conn.calls
        if "INSERT INTO skypoints.redemption_issues" in call[0]
    )

    assert conflicts == 1
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "CONFLICTING_DUPLICATE_TXN"
    assert issue_call[1][0]["ingestion_batch_id"] == 42
