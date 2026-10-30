from datetime import date

from src.utils import (
    INVALID_DATE,
    calculate_age,
    calculate_stale_member,
    normalize_date,
)


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


def test_invalid_dates():
    assert normalize_date("2021-13-13") == INVALID_DATE
    assert normalize_date("20241315") == INVALID_DATE


def test_missing_dates():
    assert normalize_date(None) is None
    assert normalize_date("") is None
    assert normalize_date("NULL") is None


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
