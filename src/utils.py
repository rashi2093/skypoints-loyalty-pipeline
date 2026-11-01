from datetime import date, datetime
import pandas as pd

INVALID_DATE = "INVALID_DATE"


def normalize_date(value, slash_format="%m/%d/%Y"):
    """Normalize supported source date formats to datetime.date."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value_str = str(value).strip()
    if value_str.lower() in ("", "nat", "none", "nan", "null"):
        return None
    if value_str.endswith(".0") and value_str[:-2].isdigit():
        value_str = value_str[:-2]
    if len(value_str) == 8 and value_str.isdigit() and value_str[:2] in ("19", "20"):
        try:
            return datetime.strptime(value_str, "%Y%m%d").date()
        except ValueError:
            return INVALID_DATE
    if value_str.isdigit() and len(value_str) in (7, 8):
        try:
            return datetime.strptime(value_str.zfill(8), "%m%d%Y").date()
        except ValueError:
            return INVALID_DATE
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", slash_format):
        try:
            return datetime.strptime(value_str, fmt).date()
        except ValueError:
            continue
    return INVALID_DATE


def calculate_age(dob, reference_date=None):
    if not isinstance(dob, date):
        return None
    reference_date = reference_date or date.today()
    return reference_date.year - dob.year - ((reference_date.month, reference_date.day) < (dob.month, dob.day))


def calculate_stale_member(flight_date, reference_date=None):
    """More than 90 days since flight => Y; 90 days or fewer => N."""
    if not isinstance(flight_date, date):
        return None
    reference_date = reference_date or date.today()
    return "Y" if (reference_date - flight_date).days > 90 else "N"
