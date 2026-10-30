from datetime import date

import pandas as pd
import pytest

from main import transform_source_row, validate_and_flatten_redemptions
from src.utils import INVALID_DATE, calculate_age, calculate_stale_member, normalize_date


def test_assessment_yyyymmdd():
    assert normalize_date("20240115") == date(2024, 1, 15)


def test_usa_unpadded_numeric_dates():
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
    reference = date(2026, 10, 30)
    assert calculate_age(date(2000, 10, 30), reference) == 26
    assert calculate_age(date(2000, 11, 1), reference) == 25
    assert calculate_age(None, reference) is None


def test_stale_member_threshold():
    reference = date(2026, 10, 30)
    assert calculate_stale_member(date(2026, 7, 31), reference) == "Y"
    assert calculate_stale_member(date(2026, 8, 1), reference) == "N"
    assert calculate_stale_member(reference, reference) == "N"
    assert calculate_stale_member(None, reference) is None


def test_missing_optional_fields_do_not_reject_member():
    row = pd.Series({"ID": "1", "Name": "Sam", "EnrollmentDate": "6152022"})
    record, errors, warnings = transform_source_row(row, "USA", "USA.csv", 1)
    assert errors == []
    assert record["dob"] is None
    assert record["age"] is None
    assert record["flight_date"] is None


def test_invalid_optional_date_is_warning_not_rejection():
    row = pd.Series({"ID": "1", "Name": "Sam", "EnrollmentDate": "6152022", "DOB": "2021-13-13"})
    record, errors, warnings = transform_source_row(row, "USA", "USA.csv", 1)
    assert errors == []
    assert record["dob"] is None
    assert any("Invalid optional Date of Birth" in warning for warning in warnings)


def test_mandatory_invalid_enrollment_rejected():
    row = pd.Series({"ID": "1", "Name": "Sam", "EnrollmentDate": "2021-13-13"})
    _, errors, _ = transform_source_row(row, "USA", "USA.csv", 1)
    assert any("Invalid Enrollment Date" in error for error in errors)


def test_field_length_validation():
    row = pd.Series({"ID": "1234567890123456789", "Name": "Sam", "EnrollmentDate": "20240101"})
    _, errors, _ = transform_source_row(row, "USA", "USA.csv", 1)
    assert any("Member ID exceeds maximum length 18" in error for error in errors)


def test_json_flattening_generic_multiple_transactions():
    feeds = [{"member_id": "123", "feed_date": "20240115", "redemptions": [
        {"txn_id": "T1", "txn_date": "20240110", "partner": "P1", "miles_redeemed": 5, "status": "COMPLETED"},
        {"txn_id": "T2", "txn_date": "20240111", "partner": "P2", "miles_redeemed": 0, "status": "PENDING"},
    ]}]
    rows, issues = validate_and_flatten_redemptions(feeds)
    assert len(rows) == 2
    assert issues == []
    assert rows[0]["txn_id"] == "T1"


def test_json_validation_rejects_bad_transaction_but_keeps_valid_one():
    feeds = [{"member_id": "123", "feed_date": "20240115", "redemptions": [
        {"txn_id": "T1", "txn_date": "20240110", "partner": "P1", "miles_redeemed": 5, "status": "COMPLETED"},
        {"txn_id": "T2", "txn_date": "20240111", "partner": "P2", "miles_redeemed": -1, "status": "PENDING"},
    ]}]
    rows, issues = validate_and_flatten_redemptions(feeds)
    assert len(rows) == 1
    assert len(issues) == 1
    assert "non-negative integer" in issues[0]["issue_detail"]


def test_json_missing_redemptions_array_is_reported():
    rows, issues = validate_and_flatten_redemptions([{"member_id": "123", "feed_date": "20240115"}])
    assert rows == []
    assert any("redemptions must be an array" in issue["issue_detail"] for issue in issues)
