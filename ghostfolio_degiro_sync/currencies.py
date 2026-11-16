"""Destination currency evidence and exact, independently sourced monetary units."""

from collections.abc import Mapping
from decimal import Decimal
from importlib.resources import files
from typing import Any, cast

import yaml

from ghostfolio_degiro_sync.models import CurrencyEvidence


def load_units() -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(files("ghostfolio_degiro_sync").joinpath("currency-units.yaml").read_text())
    if not isinstance(document, dict) or document.get("format") != 1 or not isinstance(document.get("currencies"), dict):
        raise RuntimeError("Invalid packaged currency reference")
    for code, entry in document["currencies"].items():
        if (not isinstance(code, str) or not isinstance(entry, dict)
                or set(entry) != {"minor_digits", "root", "factor"}
                or entry["root"] not in document["currencies"]
                or type(entry["factor"]) is not int or entry["factor"] not in (1, 100)
                or (entry["minor_digits"] is not None
                    and (type(entry["minor_digits"]) is not int or not 0 <= entry["minor_digits"] <= 4))):
            raise RuntimeError("Invalid packaged currency reference")
    return cast(dict[str, dict[str, Any]], document["currencies"])


UNITS = load_units()


def recognized(code: object) -> bool:
    return isinstance(code, str) and code in UNITS


def quantum(code: object) -> Decimal | None:
    if not isinstance(code, str) or code not in UNITS:
        return None
    entry = UNITS[code]
    digits = UNITS[entry["root"]]["minor_digits"]
    if digits is None:
        return None
    return Decimal(1).scaleb(-digits) * Decimal(entry["factor"])


def quote_factor(source: object, quote: object) -> Decimal:
    if (not isinstance(source, str) or not isinstance(quote, str)
            or quantum(source) is None or quantum(quote) is None
            or UNITS[source]["root"] != UNITS[quote]["root"]):
        raise RuntimeError("Unverified or conflicting Yahoo quote units")
    return Decimal(UNITS[quote]["factor"]) / Decimal(UNITS[source]["factor"])


def effective_currency(row: Mapping[str, Any]) -> CurrencyEvidence:
    raw = row.get("currency")
    value = raw
    origin = "activity"
    reason = None
    if "currency" not in row:
        reason = "Missing activity currency field"
    elif raw is None:
        origin = "assetProfile" if "assetProfile" in row else "SymbolProfile"
        profile = row.get(origin)
        if (not isinstance(profile, dict) or not isinstance(profile.get("symbol"), str)
                or not profile["symbol"].strip() or profile.get("dataSource") not in ("YAHOO", "MANUAL")):
            reason = "Unproved activity profile currency"
            value = None
        else:
            value = profile.get("currency")
    if reason is None and not recognized(value):
        reason = "Missing or unsupported activity currency"
    return {"raw": raw, "effective": value if reason is None and isinstance(value, str) else None,
            "provenance": origin, "reason": reason}
