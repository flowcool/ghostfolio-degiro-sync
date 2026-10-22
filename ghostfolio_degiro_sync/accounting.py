"""Exact financial input validation."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, cast

# Observed placeholders only; nonzero cash in these currencies is not authorized.
CASH_CURRENCIES = frozenset({"CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "USD"})

API_FORMAT_ERRORS = {
    "legacy_cash": "DEGIRO import blocked: legacy monetary-fund API format is unsupported",
    "financial_schema": "DEGIRO import blocked: incompatible execution financial fields",
    "fx_schema": "DEGIRO import blocked: incompatible execution FX format",
    "unknown": "DEGIRO import blocked: unrecognized API history format",
}


def financial_decimal(value: object) -> Decimal:
    """Reject absent, boolean and non-finite financial values without echoing data."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise RuntimeError("Invalid financial value")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise RuntimeError("Invalid financial value") from None
    if not result.is_finite() or (result and not -300 < result.adjusted() < 16):
        raise RuntimeError("Invalid financial value")
    return result


def check_api_import_format(snapshot: object) -> None:
    """Recognize contract incompatibility, never infer an API version from age."""
    if not isinstance(snapshot, dict):
        raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    for collection in ("transactions", "cash_movements"):
        rows = snapshot.get(collection)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    if any(row.get("type") in ("CASH_FUND_NAV_CHANGE", "CASH_FUND_TRANSACTION")
           for row in snapshot["cash_movements"]):
        raise RuntimeError(API_FORMAT_ERRORS["legacy_cash"])
    fields = ("quantity", "price", "total", "totalInBaseCurrency", "fxRate",
              "grossFxRate", "feeInBaseCurrency", "autoFxFeeInBaseCurrency",
              "totalFeesInBaseCurrency")
    for row in snapshot["transactions"]:
        try:
            numbers = {field: financial_decimal(row.get(field)) for field in fields}
        except RuntimeError:
            raise RuntimeError(API_FORMAT_ERRORS["financial_schema"]) from None
        if numbers["fxRate"] <= 0 or numbers["grossFxRate"] <= 0:
            raise RuntimeError(API_FORMAT_ERRORS["fx_schema"])


def broker_identity(value: object) -> str:
    if (isinstance(value, bool) or not isinstance(value, (int, str))
            or not re.fullmatch(r"[1-9][0-9]*", str(value))):
        raise RuntimeError("Invalid DEGIRO identity")
    return str(value)


def named_values(rows: Any) -> dict[str, Any]:
    """Extract broker named fields without last-value-wins ambiguity."""
    if not isinstance(rows, list):
        raise RuntimeError("Invalid DEGIRO named cash fields")
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not row["name"] or row["name"] in result
                or ("isAdded" in row and row["isAdded"] is not True)):
            raise RuntimeError("Missing or duplicate DEGIRO named cash field")
        # Optional accruedInterest is observed without a value key. Required
        # monetary fields still fail financial_decimal(None), never become zero.
        result[row["name"]] = row.get("value")
    return result


def cash_wrapper_rows(update: Any, name: str) -> list[dict[str, Any]]:
    wrapper = update[name]
    if (not isinstance(wrapper, dict) or wrapper.get("name", name) != name
            or ("isAdded" in wrapper and wrapper["isAdded"] is not True)
            or not isinstance(wrapper.get("value"), list)):
        raise RuntimeError("Invalid or removed DEGIRO cash wrapper")
    rows = wrapper["value"]
    if any(not isinstance(row, dict) or ("isAdded" in row and row["isAdded"] is not True)
           for row in rows):
        raise RuntimeError("Invalid or removed DEGIRO cash row")
    return cast(list[dict[str, Any]], rows)
