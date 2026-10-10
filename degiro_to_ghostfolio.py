#!/usr/bin/env python3
"""Read-only DEGIRO adapter; activity writes require the remaining validation gates."""

import argparse
from collections import Counter
import csv
import io
import fcntl
import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
import json
import logging
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
import yaml

import ghostfolio_core as core


log = logging.getLogger(__name__)
BROKER_TIMEOUT = (10, 30)
MAX_HISTORY_WINDOWS = 120
AUTH_FAILURE_REASONS = ("transport_error", "timeout", "tls_error", "redirect_refused",
                        "maintenance", "captcha_required", "totp_required", "in_app_required",
                        "http_400", "http_401", "http_403", "http_429", "http_5xx",
                        "invalid_login_response", "broker_rejected")
BROKER_PATHS = {
    "POST": (r"/login/secure/login/totp", r"/product_search/secure/v5/products/info"),
    "GET": (r"/pa/secure/client", r"/portfolio-reports/secure/v4/transactions",
            r"/portfolio-reports/secure/v4/order-history",
            r"/portfolio-reports/secure/v6/accountoverview",
            r"/portfolio-reports/secure/v3/cashAccountReport/csv",
            r"/trading/secure/v5/account/info/[0-9]+;jsessionid=[^/]+",
            r"/trading/secure/v5/update/[0-9]+;jsessionid=[^/]+"),
    "PUT": (r"/trading/secure/logout;jsessionid=[^/]+",),
}


# Deliberately limited to the characterized major currencies. Minor quotes
# require separate broker evidence; an IBKR suffix rule is not DEGIRO evidence.
CURRENCY_QUANTA = {"EUR": Decimal("0.01"), "USD": Decimal("0.01"), "JPY": Decimal("1")}
# Observed broker currency placeholders; exclusion requires an explicit zero CASH row.
# This does not authorize nonzero cash or security quote units in additional currencies.
CASH_CURRENCIES = frozenset({"CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "USD"})
TRADE_FIELDS = ("accountId", "comment", "currency", "dataSource", "date", "fee",
                "quantity", "symbol", "type", "unitPrice")
API_FORMAT_ERRORS = {
    "legacy_cash": "DEGIRO import blocked: legacy monetary-fund API format is unsupported",
    "financial_schema": "DEGIRO import blocked: incompatible execution financial fields",
    "fx_schema": "DEGIRO import blocked: incompatible execution FX format",
    "unknown": "DEGIRO import blocked: unrecognized API history format",
}


def check_api_import_format(snapshot):
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


def financial_decimal(value):
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


def broker_identity(value):
    if (isinstance(value, bool) or not isinstance(value, (int, str))
            or not re.fullmatch(r"[1-9][0-9]*", str(value))):
        raise RuntimeError("Invalid DEGIRO identity")
    return str(value)


def execution_comment(source_account, execution_id):
    return f"DEGIRO#{broker_identity(source_account)}:TRADE:{broker_identity(execution_id)}"


def broker_instant(value):
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise RuntimeError("DEGIRO timestamp requires an explicit offset")
    return parsed.astimezone(timezone.utc).isoformat()


def valid_isin(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        return False
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def convert_trade_to_activity(trade, product, source_account, target_account,
                              base_currency, mapping, quote_currencies):
    """Normalize one execution; no ticker fallback, unit inference or fee clamping."""
    if not isinstance(trade, dict) or not isinstance(product, dict):
        raise RuntimeError("Invalid DEGIRO execution metadata")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    comment = execution_comment(source_account, trade.get("id"))
    product_id = broker_identity(trade.get("productId"))
    if broker_identity(product.get("id")) != product_id:
        raise RuntimeError("DEGIRO product identity mismatch")
    if product.get("productType") != "STOCK" or financial_decimal(product.get("contractSize")) != 1:
        raise RuntimeError("Unverified DEGIRO instrument units")
    if trade.get("transfered") not in (None, False):
        raise RuntimeError("DEGIRO transfer execution is unsupported")
    isin = product.get("isin")
    if not valid_isin(isin):
        raise RuntimeError("Invalid DEGIRO product ISIN")
    symbol = mapping.get(isin)
    if not isinstance(symbol, str) or not symbol.strip() or symbol != symbol.strip():
        raise RuntimeError("DEGIRO ISIN requires an explicit Yahoo mapping")
    currency = product.get("currency")
    if currency not in CURRENCY_QUANTA or base_currency not in CURRENCY_QUANTA:
        raise RuntimeError("Unverified DEGIRO currency units")
    if quote_currencies.get(symbol) != currency:
        raise RuntimeError("Unverified or conflicting Yahoo quote units")
    side = trade.get("buysell")
    quantity = financial_decimal(trade.get("quantity"))
    price = financial_decimal(trade.get("price"))
    total = financial_decimal(trade.get("total"))
    base_total = financial_decimal(trade.get("totalInBaseCurrency"))
    if (side not in ("B", "S") or not quantity or price <= 0
            or (side == "B" and (quantity <= 0 or total >= 0 or base_total >= 0))
            or (side == "S" and (quantity >= 0 or total <= 0 or base_total <= 0))):
        raise RuntimeError("Inconsistent DEGIRO execution side or signs")
    if abs(total + quantity * price) > CURRENCY_QUANTA[currency]:
        raise RuntimeError("DEGIRO execution total does not match price and quantity")
    fx = financial_decimal(trade.get("fxRate"))
    gross_fx = financial_decimal(trade.get("grossFxRate"))
    if fx <= 0 or gross_fx <= 0:
        raise RuntimeError("Invalid DEGIRO FX rate")
    if currency == base_currency and (fx != 1 or gross_fx != 1):
        raise RuntimeError("Unexpected same-currency DEGIRO FX rate")
    if any(abs(total / rate - base_total) > CURRENCY_QUANTA[base_currency]
           for rate in (fx, gross_fx)):
        raise RuntimeError("DEGIRO FX direction or base total is inconsistent")
    brokerage = financial_decimal(trade.get("feeInBaseCurrency"))
    autofx = financial_decimal(trade.get("autoFxFeeInBaseCurrency"))
    fees = financial_decimal(trade.get("totalFeesInBaseCurrency"))
    if any(value > 0 for value in (brokerage, autofx, fees)) or fees != brokerage + autofx:
        raise RuntimeError("Inconsistent DEGIRO execution fees")
    for field, expected in (("totalPlusFeeInBaseCurrency", base_total + brokerage),
                            ("totalPlusAllFeesInBaseCurrency", base_total + fees)):
        if field in trade and abs(financial_decimal(trade[field]) - expected) > CURRENCY_QUANTA[base_currency]:
            raise RuntimeError("Inconsistent DEGIRO net execution total")
    activity = {"accountId": target_account, "comment": comment, "currency": currency,
                "dataSource": "YAHOO", "date": broker_instant(trade.get("date")),
                "fee": float(-fees * fx), "quantity": float(abs(quantity)), "symbol": symbol,
                "type": "BUY" if side == "B" else "SELL", "unitPrice": float(price)}
    if any(not isfinite(activity[field]) or (activity[field] == 0 and value != 0)
           for field, value in (("fee", fees), ("quantity", quantity), ("unitPrice", price))):
        raise RuntimeError("DEGIRO execution cannot be represented safely")
    return activity


def normalize_trades(snapshot, target_account, mapping, quote_currencies):
    """Keep individual fills and reject conflicting duplicate execution identities."""
    rows = []
    merge_history(rows, snapshot["transactions"])
    result = []
    for trade in rows:
        product_id = broker_identity(trade.get("productId"))
        product = snapshot["products"].get(product_id)
        result.append(convert_trade_to_activity(trade, product, snapshot["source_account"],
            target_account, snapshot["account_info"]["baseCurrency"], mapping, quote_currencies))
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def trade_signature(activity):
    """Compare canonical financial content independently of server IDs/metadata."""
    try:
        values = dict(activity)
        values["date"] = broker_instant(values["date"])
        for field in ("fee", "quantity", "unitPrice"):
            values[field] = financial_decimal(values[field])
        if (values["type"] not in ("BUY", "SELL") or values["dataSource"] != "YAHOO"
                or values["quantity"] <= 0 or values["unitPrice"] <= 0 or values["fee"] < 0):
            raise RuntimeError("Invalid existing Ghostfolio trade")
        return tuple(values[field] for field in TRADE_FIELDS)
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Invalid existing Ghostfolio trade") from None


def reconcile_trade_holdings(activities, existing, quantities):
    """Pure account/symbol guard; manual overlap needs explicit reconciliation.

    Existing contains active target activities; quantities is the active holding
    baseline keyed by (target account, Yahoo symbol). Future orchestration owns
    the complete/redaction-checked read, never this pure function.
    """
    identities = {}
    manual = []
    for activity in existing:
        key = (activity.get("accountId"), activity.get("comment"))
        if isinstance(key[1], str) and re.fullmatch(r"DEGIRO#[1-9][0-9]*:TRADE:[1-9][0-9]*", key[1]):
            signature = trade_signature(activity)
            if key in identities and identities[key] != signature:
                raise RuntimeError("Conflicting existing DEGIRO identity")
            if key in identities:
                raise RuntimeError("Duplicate existing DEGIRO identity")
            identities[key] = signature
        elif activity.get("type") in ("BUY", "SELL"):
            manual.append(activity)
    balances = {key: financial_decimal(value) for key, value in quantities.items()}
    pending = []
    seen = {}
    for activity in sorted(activities, key=lambda item: (broker_instant(item["date"]), item["comment"])):
        key = (activity["accountId"], activity["comment"])
        signature = trade_signature(activity)
        if key in seen:
            if seen[key] != signature:
                raise RuntimeError("Conflicting pending DEGIRO identity")
            continue
        seen[key] = signature
        if key in identities:
            if identities[key] != signature:
                raise RuntimeError("Existing DEGIRO identity changed financial content")
            continue
        # Proximity is a blocker, never evidence that two executions are equal.
        for candidate in manual:
            if (candidate.get("accountId"), candidate.get("symbol"), candidate.get("type")) != (
                    activity["accountId"], activity["symbol"], activity["type"]):
                continue
            gap = abs((datetime.fromisoformat(broker_instant(candidate.get("date"))).date()
                       - datetime.fromisoformat(activity["date"]).date()).days)
            if gap <= 2:
                raise RuntimeError("Manual Ghostfolio trade requires explicit reconciliation")
        holding_key = (activity["accountId"], activity["symbol"])
        quantity = financial_decimal(activity["quantity"])
        balances[holding_key] = balances.get(holding_key, Decimal(0)) + (
            quantity if activity["type"] == "BUY" else -quantity)
        if balances[holding_key] < 0:
            raise RuntimeError("DEGIRO trades would create a negative target holding")
        pending.append(activity)
    return pending


def load_cash_rules(path=None):
    """Read the reviewed local taxonomy; malformed rules never broaden matching."""
    path = Path(path) if path is not None else Path(__file__).with_name("cash-rules.yaml")
    try:
        document = yaml.safe_load(path.read_text())
        rules = document["rules"]
        if document["format"] != 1 or not isinstance(rules, dict) or not rules:
            raise ValueError
        for name, rule in rules.items():
            if not isinstance(name, str) or not isinstance(rule, dict):
                raise ValueError
            if not isinstance(rule.get("type"), str) or not rule["type"]:
                raise ValueError
            descriptions = [key for key in ("description_exact", "description_pattern") if key in rule]
            if len(descriptions) != 1 or not isinstance(rule[descriptions[0]], str):
                raise ValueError
            if "description_pattern" in rule:
                pattern = rule["description_pattern"]
                if not pattern.startswith("^") or not pattern.endswith("$"):
                    raise ValueError
                re.compile(pattern)
            if rule.get("sign") not in (None, "positive", "negative"):
                raise ValueError
            for flag in ("product_required", "order_required"):
                if flag in rule and type(rule[flag]) is not bool:
                    raise ValueError
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError, re.error):
        raise RuntimeError("Invalid DEGIRO cash rules") from None
    return rules


def classify_cash_movements(rows, rules=None):
    """Classify the entire ledger; preserve row identity and reject ambiguity."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Invalid DEGIRO cash ledger")
    rules = load_cash_rules() if rules is None else rules
    unique = []
    merge_history(unique, rows, cash=True)
    result = {name: [] for name in rules}
    for row in unique:
        broker_identity(row.get("id"))
        broker_instant(row.get("date"))
        description = row.get("description")
        if not isinstance(description, str):
            raise RuntimeError("Invalid DEGIRO cash description")
        matches = [name for name, rule in rules.items() if row.get("type") == rule["type"] and
                   (description == rule["description_exact"] if "description_exact" in rule else
                    re.fullmatch(rule["description_pattern"], description))]
        if len(matches) != 1:
            raise RuntimeError("Unknown or ambiguous DEGIRO cash category")
        name = matches[0]
        rule = rules[name]
        if rule.get("treatment") == "nonfinancial_notice":
            if row.get("change") is not None:
                raise RuntimeError("DEGIRO cash notice unexpectedly contains an amount")
        else:
            amount = financial_decimal(row.get("change"))
            currency = row.get("currency")
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                raise RuntimeError("Invalid DEGIRO cash currency")
            broker_instant(row.get("valueDate"))
            if ((not amount and rule.get("treatment") not in ("unsupported_blocking", "zero_interest"))
                    or (rule.get("sign") == "positive" and amount <= 0)
                    or (rule.get("sign") == "negative" and amount >= 0)):
                raise RuntimeError("Unsupported DEGIRO cash sign or reversal")
            if rule.get("treatment") in ("zero_interest", "positive_compensation"):
                validate_cash_yield(row, name, rule["treatment"])
        if rule.get("product_required"):
            broker_identity(row.get("productId"))
        if rule.get("order_required") and (
                not isinstance(row.get("orderId"), str) or not row["orderId"].strip()):
            raise RuntimeError("Missing DEGIRO cash order relation")
        result[name].append(row)
    return result


def validate_cash_yield(row, category, treatment):
    """Only characterized EUR receipts; no inferred taxes, FX or product links."""
    expected = {"flatex_interest": "zero_interest",
                "monetary_fund_compensation": "positive_compensation"}
    allowed = {"id", "type", "description", "change", "currency", "date",
               "valueDate", "balance", "productId", "orderId"}
    amount = financial_decimal(row["change"])
    if (expected.get(category) != treatment or set(row) - allowed
            or row.get("productId") is not None or row.get("orderId") not in (None, "")
            or row["currency"] != "EUR" or amount % CURRENCY_QUANTA["EUR"] != 0
            or (treatment == "zero_interest" and amount != 0)
            or (treatment == "positive_compensation" and amount <= 0)):
        raise RuntimeError("Unverified DEGIRO cash yield blocks account writes")
    value = float(amount)
    if not isfinite(value) or Decimal(str(value)) != amount:
        raise RuntimeError("DEGIRO cash yield cannot be represented safely")


def normalize_cash_yield(snapshot, target_account, rules=None):
    """Retain zero interest and distinct compensation receipts without cash effects."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    source = broker_identity(snapshot["source_account"])
    result = []
    for category, kind, label in (("flatex_interest", "INTEREST", "FLATEX_INTEREST"),
                                 ("monetary_fund_compensation", "COMPENSATION", "MMF_COMPENSATION")):
        for row in classified.get(category, []):
            validate_cash_yield(row, category, rules[category].get("treatment"))
            if snapshot["account_info"]["baseCurrency"] != "EUR":
                raise RuntimeError("Unverified DEGIRO cash yield account currency")
            result.append({"accountId": target_account,
                "comment": f"DEGIRO#{source}:{kind}:{broker_identity(row['id'])}",
                "currency": "EUR", "dataSource": "MANUAL", "date": broker_instant(row["date"]),
                "fee": 0, "quantity": 1, "symbol": f"GF_DEGIRO_{source}_{label}_EUR",
                "type": "INTEREST", "unitPrice": float(financial_decimal(row["change"]))})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def associate_dividends(classified):
    """One observed payment and one withholding per exact association group."""
    groups = {}
    for category in ("paid_dividend", "dividend_withholding"):
        for row in classified.get(category, []):
            if row.get("orderId") not in (None, ""):
                raise RuntimeError("Unverified DEGIRO dividend relation")
            key = (broker_identity(row.get("productId")), row["currency"],
                   broker_instant(row.get("date")), broker_instant(row.get("valueDate")))
            groups.setdefault(key, {"paid_dividend": [], "dividend_withholding": []})[category].append(row)
    pairs = []
    for group in groups.values():
        if len(group["paid_dividend"]) != 1 or len(group["dividend_withholding"]) != 1:
            raise RuntimeError("Ambiguous or unverified DEGIRO dividend withholding")
        dividend = group["paid_dividend"][0]
        withholding = group["dividend_withholding"][0]
        if -financial_decimal(withholding["change"]) > financial_decimal(dividend["change"]):
            raise RuntimeError("DEGIRO withholding exceeds gross payment")
        pairs.append((dividend, withholding))
    return pairs


def normalize_dividends(snapshot, target_account, mapping, quote_currencies, rules=None):
    """Import paid cash amounts independently of current or historical holdings."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    result = []
    for dividend, withholding in associate_dividends(classified):
        product_id = broker_identity(dividend["productId"])
        product = snapshot["products"].get(product_id)
        if (not isinstance(product, dict) or broker_identity(product.get("id")) != product_id
                or product.get("productType") != "STOCK"
                or financial_decimal(product.get("contractSize")) != 1):
            raise RuntimeError("Unverified DEGIRO dividend instrument")
        isin = product.get("isin")
        if not valid_isin(isin):
            raise RuntimeError("Invalid DEGIRO dividend ISIN")
        symbol = mapping.get(isin)
        if not isinstance(symbol, str) or not symbol.strip() or symbol != symbol.strip():
            raise RuntimeError("DEGIRO dividend requires an explicit Yahoo mapping")
        currency = dividend["currency"]
        if (currency not in CURRENCY_QUANTA or product.get("currency") != currency
                or quote_currencies.get(symbol) != currency):
            raise RuntimeError("Unverified DEGIRO dividend currency or quote units")
        gross = float(financial_decimal(dividend["change"]))
        tax = float(-financial_decimal(withholding["change"]))
        if not isfinite(gross) or gross <= 0 or not isfinite(tax) or tax <= 0:
            raise RuntimeError("DEGIRO dividend cannot be represented safely")
        result.append({"accountId": target_account,
            "comment": f"DEGIRO#{broker_identity(snapshot['source_account'])}:DIVIDEND:{broker_identity(dividend['id'])}",
            "currency": currency, "dataSource": "YAHOO", "date": broker_instant(dividend["date"]),
            "fee": tax, "quantity": 1, "symbol": symbol, "type": "DIVIDEND", "unitPrice": gross})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def reconcile_execution_costs(classified, transactions, base_currency):
    """A brokerage ledger debit must evidence one already included execution fee."""
    executions = []
    merge_history(executions, transactions)
    matched = set()
    for row in classified.get("trade_commission", []):
        candidates = [trade for trade in executions
            if broker_identity(trade.get("productId")) == broker_identity(row["productId"])
            and broker_instant(trade.get("date")) == broker_instant(row["date"])]
        if len(candidates) != 1 or row["currency"] != base_currency:
            raise RuntimeError("Unverified or ambiguous DEGIRO execution cost")
        trade = candidates[0]
        identity = broker_identity(trade.get("id"))
        brokerage = financial_decimal(trade.get("feeInBaseCurrency"))
        autofx = financial_decimal(trade.get("autoFxFeeInBaseCurrency"))
        total = financial_decimal(trade.get("totalFeesInBaseCurrency"))
        if (identity in matched or brokerage >= 0 or autofx > 0
                or total != brokerage + autofx or financial_decimal(row["change"]) != brokerage
                or (trade.get("orderId") is not None and trade["orderId"] != row["orderId"])):
            raise RuntimeError("DEGIRO execution cost does not reconcile")
        matched.add(identity)


def normalize_fees(snapshot, target_account, rules=None):
    """Only observed autonomous connection charges; no absolute-value refunds."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    source_account = broker_identity(snapshot["source_account"])
    base_currency = snapshot["account_info"]["baseCurrency"]
    reconcile_execution_costs(classified, snapshot["transactions"], base_currency)
    result = []
    for name, rows in classified.items():
        if rules[name].get("treatment") != "standalone_fee":
            continue
        if name != "exchange_connection_fee":
            raise RuntimeError("Unverified DEGIRO autonomous fee category")
        for row in rows:
            amount = -financial_decimal(row["change"])
            if (row.get("productId") is not None or row.get("orderId") not in (None, "")
                    or row["currency"] != "EUR" or base_currency != "EUR"
                    or amount <= 0 or amount % CURRENCY_QUANTA["EUR"] != 0):
                raise RuntimeError("Unverified DEGIRO autonomous fee relation or units")
            fee = float(amount)
            if not isfinite(fee) or fee <= 0 or Decimal(str(fee)) != amount:
                raise RuntimeError("DEGIRO autonomous fee cannot be represented safely")
            result.append({"accountId": target_account,
                "comment": f"DEGIRO#{source_account}:FEE:{broker_identity(row['id'])}",
                "currency": "EUR", "dataSource": "MANUAL", "date": broker_instant(row["date"]),
                "fee": fee, "quantity": 1,
                "symbol": f"GF_DEGIRO_{source_account}_EXCHANGE_CONNECTION_EUR",
                "type": "FEE", "unitPrice": 0})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def named_values(rows):
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


def cash_wrapper_rows(update, name):
    wrapper = update[name]
    if (not isinstance(wrapper, dict) or wrapper.get("name", name) != name
            or ("isAdded" in wrapper and wrapper["isAdded"] is not True)
            or not isinstance(wrapper.get("value"), list)):
        raise RuntimeError("Invalid or removed DEGIRO cash wrapper")
    rows = wrapper["value"]
    if any(not isinstance(row, dict) or ("isAdded" in row and row["isAdded"] is not True)
           for row in rows):
        raise RuntimeError("Invalid or removed DEGIRO cash row")
    return rows


def current_cash_balance(snapshot, target_account, source_account, now=None):
    """Validate the observed EUR current snapshot; aliases are cross-checks only."""
    now = datetime.now(timezone.utc) if now is None else now
    try:
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise RuntimeError("Cash validation requires an aware current time")
        started = datetime.fromisoformat(broker_instant(snapshot["fetch_started_at"]))
        fetched = datetime.fromisoformat(broker_instant(snapshot["fetched_at"]))
        if not now - timedelta(minutes=5) <= started <= fetched <= now:
            raise RuntimeError("DEGIRO cash snapshot is stale or has invalid timing")
        if broker_identity(snapshot["source_account"]) != broker_identity(source_account):
            raise RuntimeError("DEGIRO cash source account mismatch")
        if (not isinstance(target_account, dict) or not isinstance(target_account.get("id"), str)
                or not target_account["id"].strip()):
            raise RuntimeError("Missing Ghostfolio cash target account")
        currency = snapshot["account_info"]["baseCurrency"]
        if currency != "EUR" or target_account.get("currency") != currency:
            raise RuntimeError("Unverified or mismatched cash account currencies")
        rules = load_cash_rules()
        classified = classify_cash_movements(snapshot["cash_movements"], rules)
        if any(classified[name] for name, rule in rules.items()
               if rule.get("treatment") == "unsupported_blocking"):
            raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
        update = snapshot["update"]
        total = named_values(cash_wrapper_rows(update, "totalPortfolio"))
        balance = financial_decimal(total["totalCash"])
        degiro = financial_decimal(total["degiroCash"])
        flatex = financial_decimal(total["flatexCash"])
        settlement = financial_decimal(total["pendingSettlement"])
        if (balance < 0 or degiro != 0 or flatex != balance or degiro + flatex != balance
                or settlement != 0 or balance % CURRENCY_QUANTA["EUR"] != 0):
            raise RuntimeError("Unverified or inconsistent DEGIRO cash totals or settlement")
        if "cryptoTotalCash" in total and financial_decimal(total["cryptoTotalCash"]) != balance:
            raise RuntimeError("Conflicting DEGIRO cash alias")
        funds = {}
        fund_rows = cash_wrapper_rows(update, "cashFunds")
        for row in fund_rows:
            fields = named_values(row["value"])
            code = fields["currencyCode"]
            if (not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code)
                    or code in funds):
                raise RuntimeError("Invalid or duplicate DEGIRO cash fund currency")
            funds[code] = financial_decimal(fields["value"])
        if funds.get(currency) != balance or any(value != 0 for code, value in funds.items() if code != currency):
            raise RuntimeError("DEGIRO cash funds disagree or contain foreign cash")
        positions = cash_wrapper_rows(update, "portfolio")
        cash_positions = set()
        for row in positions:
            identity = row.get("id")
            if isinstance(identity, str) and identity.startswith("FLATEX_"):
                fields = named_values(row["value"])
                if identity in cash_positions or fields.get("id") != identity:
                    raise RuntimeError("Conflicting DEGIRO cash pseudo-position identity")
                cash_positions.add(identity)
                if identity != "FLATEX_EUR" and financial_decimal(fields["size"]) != 0:
                    raise RuntimeError("Unverified foreign DEGIRO cash pseudo-position")
        matches = [row for row in positions if row.get("id") == "FLATEX_EUR"]
        if len(matches) != 1:
            raise RuntimeError("Missing or duplicate DEGIRO cash pseudo-position")
        fields = named_values(matches[0]["value"])
        if fields.get("id") != "FLATEX_EUR" or financial_decimal(fields["size"]) != balance:
            raise RuntimeError("DEGIRO cash pseudo-position disagrees")
        represented = float(balance)
        if not isfinite(represented) or Decimal(str(represented)) != balance:
            raise RuntimeError("DEGIRO cash balance cannot be represented safely")
        return represented
    except (KeyError, TypeError, AttributeError):
        raise RuntimeError("Missing or malformed DEGIRO current cash evidence") from None


def apply_cash_balance(snapshot, target_account, source_account, update_balance,
                       dry_run=True, import_ok=False, uncertain=False, now=None):
    """C11 binds the URL-validated writer; no callback runs without clean evidence."""
    if type(dry_run) is not bool or type(uncertain) is not bool or import_ok is not True or uncertain:
        raise RuntimeError("Ambiguous or unsuccessful account import blocks cash update")
    balance = current_cash_balance(snapshot, target_account, source_account, now)
    if not dry_run:
        if not callable(update_balance) or update_balance(target_account["id"], balance) is not True:
            raise RuntimeError("Ghostfolio cash update did not confirm success")
    return balance


def validate_ghost_host(host):
    """Exact operator origins; fixed errors never expose URL userinfo or tokens."""
    allowed = {"https://ghost.mylittlemess.fr", "http://ghostfolio:3333",
               "http://localhost:3333", "http://127.0.0.1:3333"}
    if not isinstance(host, str) or host not in allowed:
        raise RuntimeError("Ghostfolio target URL is outside the approved origin policy")
    return host


@contextmanager
def ghost_transport(config, target_account):
    """Bind immutable core to bounded HTTP for this sequential single-thread run."""
    host = validate_ghost_host(config.get("ghost_host"))
    token = config.get("ghost_token")
    dry_run = config.get("dry_run", True)
    if (not isinstance(token, str) or not token.strip() or "\r" in token or "\n" in token
            or type(dry_run) is not bool or not isinstance(target_account, dict)
            or not isinstance(target_account.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", target_account["id"])):
        raise RuntimeError("Invalid Ghostfolio transport configuration")
    session = requests.Session()
    session.trust_env = False
    session.headers.update(core.ghost_headers(token))
    session.RequestException = requests.RequestException
    original_send = session.send
    account_path = f"/api/v1/account/{target_account['id']}"

    def send(request, **kwargs):
        parts = urlsplit(request.url)
        origin = f"{parts.scheme}://{parts.netloc}"
        allowed = (request.method == "GET" and parts.path in
                   ("/api/v1/account", "/api/v1/activities", account_path)) or (
                   not dry_run and request.method == "POST" and parts.path == "/api/v1/import") or (
                   not dry_run and request.method == "PUT" and parts.path == account_path)
        if origin != host or parts.query or parts.fragment or not allowed:
            raise RuntimeError("Ghostfolio request outside the approved sync boundary")
        kwargs.update(timeout=(10, 60), allow_redirects=False, verify=True, stream=False)
        try:
            response = original_send(request, **kwargs)
        except requests.RequestException:
            raise requests.RequestException("Ghostfolio bounded transport failed") from None
        if 300 <= response.status_code < 400:
            raise requests.RequestException("Ghostfolio redirect refused")
        if request.method == "GET" and parts.path == account_path and not dry_run:
            try:
                current = response.json()
            except ValueError:
                raise RuntimeError("Invalid Ghostfolio current account response") from None
            if (response.status_code != 200 or not isinstance(current, dict)
                    or current.get("id") != target_account["id"]
                    or current.get("currency") != target_account.get("currency")
                    or not core.activity_is_active({"account": current}) or current.get("balance") is None):
                raise RuntimeError("Ghostfolio cash account changed or is redacted")
            financial_decimal(current["balance"])
        return response

    session.send = send
    previous_requests = core.requests
    saved_log = (core.log.disabled, core.log.propagate)
    core.requests = session
    # Immutable core error logs can include HTTP bodies/exception URLs. The
    # adapter emits controlled outcome messages instead of forwarding them.
    core.log.disabled = True
    core.log.propagate = False
    try:
        yield session
    finally:
        core.requests = previous_requests
        core.log.disabled, core.log.propagate = saved_log
        session.close()


def existing_activity_context(body, target_account):
    """Complete unredacted list; never discard ownership or inactive target rows."""
    if not isinstance(body, dict) or not isinstance(body.get("activities"), list):
        raise RuntimeError("Invalid Ghostfolio activity list")
    rows = body["activities"]
    if type(body.get("count")) is not int or body["count"] != len(rows):
        raise RuntimeError("Incomplete Ghostfolio activity list")
    identities = set()
    result = []
    balances = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise RuntimeError("Invalid Ghostfolio created activity identity")
        if row["id"] in identities:
            raise RuntimeError("Duplicate Ghostfolio created activity identity")
        identities.add(row["id"])
        for field in ("quantity", "unitPrice", "fee"):
            if financial_decimal(row.get(field)) < 0:
                raise RuntimeError("Invalid or redacted Ghostfolio financial context")
        comment = row.get("comment")
        if comment is not None and not isinstance(comment, str):
            raise RuntimeError("Invalid Ghostfolio activity comment")
        profile = row["assetProfile"] if "assetProfile" in row else row.get("SymbolProfile")
        if (not isinstance(profile, dict) or not isinstance(profile.get("symbol"), str)
                or not profile["symbol"] or not isinstance(profile.get("dataSource"), str)
                or not profile["dataSource"]):
            raise RuntimeError("Missing or invalid Ghostfolio asset profile context")
        normalized = {**row, "symbol": profile["symbol"], "dataSource": profile["dataSource"]}
        broker_instant(row.get("date"))
        if row.get("accountId") != target_account["id"]:
            result.append(normalized)
            continue
        if profile["dataSource"] not in ("YAHOO", "MANUAL"):
            raise RuntimeError("Unsupported target asset data source")
        if row.get("type") not in ("BUY", "SELL", "DIVIDEND", "FEE", "INTEREST"):
            raise RuntimeError("Unsupported target activity type blocks synchronization")
        if row.get("type") == "INTEREST" and (
                profile["dataSource"] != "MANUAL" or row.get("currency") != "EUR"
                or financial_decimal(row["quantity"]) != 1 or financial_decimal(row["fee"]) != 0):
            raise RuntimeError("Unverified target interest representation")
        if not core.activity_is_active(row) or not core.activity_date_is_current(row):
            raise RuntimeError("Inactive or future target activity blocks synchronization")
        if row.get("type") in ("BUY", "SELL"):
            if profile["dataSource"] != "YAHOO":
                raise RuntimeError("Unverified target holding data source")
            quantity = financial_decimal(row["quantity"])
            key = (row["accountId"], profile["symbol"])
            balances[key] = balances.get(key, Decimal(0)) + (quantity if row["type"] == "BUY" else -quantity)
        result.append(normalized)
    if any(quantity < 0 for quantity in balances.values()):
        raise RuntimeError("Negative existing target holding blocks synchronization")
    return result, balances


def activity_signature(activity):
    """Exact normalized DTO evidence independent of server row/profile metadata."""
    try:
        values = dict(activity)
        values["date"] = broker_instant(values["date"])
        for field in ("quantity", "unitPrice", "fee"):
            values[field] = financial_decimal(values[field])
        return tuple(values[field] for field in TRADE_FIELDS)
    except (KeyError, TypeError):
        raise RuntimeError("Incomplete Ghostfolio activity evidence") from None


def validate_cash_yield_identity(activity, namespace):
    """Canonical yield identities retain exact type, units and source symbol."""
    comment = activity.get("comment")
    for kind, label in (("INTEREST", "FLATEX_INTEREST"), ("COMPENSATION", "MMF_COMPENSATION")):
        if not isinstance(comment, str) or not comment.startswith(namespace + kind + ":"):
            continue
        source = namespace.removeprefix("DEGIRO#").removesuffix(":")
        amount = financial_decimal(activity.get("unitPrice"))
        if (activity.get("type") != "INTEREST" or activity.get("dataSource") != "MANUAL"
                or activity.get("symbol") != f"GF_DEGIRO_{source}_{label}_EUR"
                or activity.get("currency") != "EUR"
                or financial_decimal(activity.get("quantity")) != 1
                or financial_decimal(activity.get("fee")) != 0
                or amount % CURRENCY_QUANTA["EUR"] != 0
                or (kind == "INTEREST" and amount != 0)
                or (kind == "COMPENSATION" and amount <= 0)):
            raise RuntimeError("Invalid canonical DEGIRO cash yield evidence")


def pending_activities(activities, existing, target_account, source_account):
    """Canonical identities never fall back to proximity or another account."""
    namespace = f"DEGIRO#{broker_identity(source_account)}:"
    known = {}
    for row in existing:
        comment = row.get("comment")
        if not isinstance(comment, str) or not comment.startswith(namespace):
            continue
        if row.get("accountId") != target_account["id"]:
            raise RuntimeError("DEGIRO identity is owned by another target account")
        if not re.fullmatch(re.escape(namespace) + r"(TRADE|DIVIDEND|FEE|INTEREST|COMPENSATION):[1-9][0-9]*", comment):
            raise RuntimeError("Malformed existing DEGIRO canonical identity")
        if comment in known:
            raise RuntimeError("Duplicate existing DEGIRO canonical identity")
        validate_cash_yield_identity(row, namespace)
        known[comment] = row
    result = []
    seen = {}
    for activity in activities:
        if activity.get("accountId") != target_account["id"]:
            raise RuntimeError("Candidate target account mismatch")
        comment = activity["comment"]
        validate_cash_yield_identity(activity, namespace)
        signature = activity_signature(activity)
        if comment in seen:
            if signature != seen[comment]:
                raise RuntimeError("Conflicting candidate DEGIRO identity")
            continue
        seen[comment] = signature
        if comment in known:
            if signature != activity_signature(known[comment]):
                raise RuntimeError("Existing DEGIRO identity changed financial evidence")
            continue
        for row in existing:
            if row.get("accountId") != target_account["id"] or row.get("type") != activity["type"]:
                continue
            old_comment = row.get("comment") or ""
            if old_comment.startswith("DEGIRO#"):
                continue
            gap = abs((datetime.fromisoformat(broker_instant(row["date"])).date()
                       - datetime.fromisoformat(activity["date"]).date()).days)
            if (gap <= 2 and (activity["type"] in ("FEE", "INTEREST") or row["symbol"] == activity["symbol"])):
                raise RuntimeError("Manual or CSV activity requires explicit reconciliation")
        result.append(activity)
    return result


def cleanup_preflight(existing_body, manifest):
    """Select exact proved broker IDs only; never perform or authorize deletion."""
    if (not isinstance(manifest, dict) or set(manifest) != {"source_account", "target_account", "activities"}
            or not isinstance(manifest["activities"], dict) or not manifest["activities"]):
        raise RuntimeError("Invalid DEGIRO cleanup manifest")
    source = broker_identity(manifest["source_account"])
    target = manifest["target_account"]
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise RuntimeError("Invalid cleanup target account")
    namespace = f"DEGIRO#{source}:"
    activities = list(manifest["activities"].values())
    for identity, activity in manifest["activities"].items():
        if (not isinstance(identity, str) or not isinstance(activity, dict) or set(activity) != set(TRADE_FIELDS)
                or activity.get("accountId") != target or activity.get("comment") != identity
                or not re.fullmatch(re.escape(namespace) + r"(TRADE|DIVIDEND|FEE|INTEREST|COMPENSATION):[1-9][0-9]*", identity)):
            raise RuntimeError("Unproved cleanup broker ownership")
        activity_signature(activity)
    rows, _ = existing_activity_context(existing_body, {"id": target})
    if pending_activities(activities, rows, {"id": target}, source):
        raise RuntimeError("Cleanup requires complete exact positive activity evidence")
    selected = {row["comment"]: row["id"] for row in rows
                if row.get("accountId") == target and row.get("comment") in manifest["activities"]}
    snapshot_hash = hashlib.sha256(json.dumps(existing_body, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"source_account": source, "target_account": target,
            "activity_ids": selected, "snapshot_sha256": snapshot_hash}


def write_journal(journal):
    """Replace private state atomically, flushing both file and directory."""
    content = yaml.safe_dump(journal["document"], sort_keys=True)
    if len(content.encode("utf-8")) > 1_000_000:
        raise RuntimeError("Synchronization journal exceeds state budget")
    descriptor, temporary = tempfile.mkstemp(dir=journal["directory"], prefix=".intent-")
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, journal["path"])
        descriptor = os.open(journal["directory"], os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_state_file(descriptor):
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise RuntimeError("Unsafe private sync state file")


@contextmanager
def account_journal(config):
    """Hold one private account lock; unresolved requests survive process exit."""
    directory = config.get("state_dir")
    if not isinstance(directory, str) or not directory:
        raise RuntimeError("Live synchronization requires private STATE_DIR")
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise RuntimeError("Unsafe private STATE_DIR")
    owner = {"host": validate_ghost_host(config.get("ghost_host")),
             "source": broker_identity(config.get("source_account")), "target": config.get("target_account")}
    if not isinstance(owner["target"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", owner["target"]):
        raise RuntimeError("Invalid journal account ownership")
    # Serialize by destination even if a second broker source is misconfigured.
    key = hashlib.sha256(json.dumps({"host": owner["host"], "target": owner["target"]},
        sort_keys=True).encode()).hexdigest()
    descriptor = os.open(directory / (key + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_state_file(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another synchronization owns this account") from None
        path = directory / (key + ".yaml")
        try:
            reader = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            document = {"version": 1, "owner": owner, "pending": None, "resolved": {}}
        else:
            with os.fdopen(reader) as source:
                private_state_file(source.fileno())
                if os.fstat(source.fileno()).st_size > 1_000_000:
                    raise RuntimeError("Synchronization journal exceeds state budget")
                document = yaml.safe_load(source.read())
            if (not isinstance(document, dict) or set(document) != {"version", "owner", "pending", "resolved"}
                    or type(document["version"]) is not int or document["version"] != 1
                    or document["owner"] != owner or not isinstance(document["resolved"], dict)
                    or document["pending"] is not None and not isinstance(document["pending"], dict)):
                raise RuntimeError("Invalid private synchronization journal")
        yield {"directory": directory, "path": path, "document": document}
    finally:
        os.close(descriptor)


def begin_intent(journal, kind, payload):
    if journal["document"]["pending"] is not None:
        raise RuntimeError("Unresolved durable write intent blocks account writes")
    identity = uuid.uuid4().hex
    journal["document"]["pending"] = {"id": identity, "kind": kind, "payload": payload}
    write_journal(journal)
    return identity


def confirm_intent(journal, identity):
    pending = journal["document"]["pending"]
    if not isinstance(pending, dict) or pending.get("id") != identity:
        raise RuntimeError("Synchronization intent identity changed")
    resolved = journal["document"]["resolved"]
    resolved[identity] = {"kind": pending["kind"],
        "at": datetime.now(timezone.utc).isoformat()}
    if len(resolved) > 1000:
        # Only confirmed audit metadata ages out; pending intent is never pruned.
        keep = sorted(resolved.items(), key=lambda item: (broker_instant(item[1]["at"]), item[0]))[-1000:]
        journal["document"]["resolved"] = dict(keep)
    journal["document"]["pending"] = None
    write_journal(journal)


def selected_import_intent(journal, expected_intent_id):
    """Select a specific import under its owner lock before obtaining evidence."""
    if (not isinstance(expected_intent_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", expected_intent_id)):
        raise RuntimeError("Invalid expected synchronization intent identity")
    pending = journal["document"]["pending"]
    if (not isinstance(pending, dict) or pending.get("kind") != "import"
            or not isinstance(pending.get("payload"), dict) or not pending["payload"]):
        raise RuntimeError("No recoverable pending import intent")
    if pending.get("id") != expected_intent_id:
        raise RuntimeError("Synchronization intent identity changed")
    return pending


def verify_import_intent(journal, config, existing_body, expected_intent_id):
    pending = selected_import_intent(journal, expected_intent_id)
    target = {"id": config["target_account"]}
    rows, _ = existing_activity_context(existing_body, target)
    candidates = list(pending["payload"].values())
    if (any(not isinstance(row, dict) or row.get("comment") != identity
            for identity, row in pending["payload"].items())
            or pending_activities(candidates, rows, target, config["source_account"])):
        raise RuntimeError("Complete exact positive readback required for recovery")
    return len(candidates)


def resolve_import_intent(config, existing_body, *, expected_intent_id):
    """Resolve one explicitly selected request using complete positive readback."""
    with account_journal(config) as journal:
        matched = verify_import_intent(journal, config, existing_body, expected_intent_id)
        confirm_intent(journal, expected_intent_id)
        return matched


def readback_import_intent(config, *, expected_intent_id, confirm=False):
    """Authenticated GET-only recovery; default preflight preserves private state."""
    if type(confirm) is not bool:
        raise RuntimeError("Invalid local recovery confirmation mode")
    readonly = {**config, "dry_run": True}
    with account_journal(readonly) as journal:
        selected_import_intent(journal, expected_intent_id)
        target = {"id": readonly["target_account"]}
        with ghost_transport(readonly, target) as session:
            response = session.get(f"{readonly['ghost_host']}/api/v1/account/{target['id']}")
            if response.status_code != 200:
                raise RuntimeError("Recovery account readback failed")
            current = response.json()
            if (not isinstance(current, dict) or current.get("id") != target["id"]
                    or not core.activity_is_active({"account": current})
                    or current.get("currency") not in CURRENCY_QUANTA
                    or current.get("balance") is None):
                raise RuntimeError("Invalid or redacted recovery account context")
            financial_decimal(current["balance"])
            response = session.get(f"{readonly['ghost_host']}/api/v1/activities")
            if response.status_code != 200:
                raise RuntimeError("Recovery activity readback failed")
            body = response.json()
        matched = verify_import_intent(journal, readonly, body, expected_intent_id)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if confirm:
            confirm_intent(journal, expected_intent_id)
        return {"matched": matched, "confirmed": confirm, "snapshot_sha256": digest}


def synchronize_account(config, snapshot, target_account, existing_body, mapping,
                        quote_currencies, import_activities, update_balance, now=None):
    """Serialize live account work and preserve intent before every write."""
    if config.get("dry_run", True) is not False and config.get("sync_mode") != "prospective":
        return synchronize_locked(config, snapshot, target_account, existing_body, mapping,
            quote_currencies, import_activities, update_balance, now=now)
    with account_journal(config) as journal:
        if journal["document"]["pending"] is not None:
            raise RuntimeError("Unresolved durable write intent blocks account writes")
        return synchronize_locked(config, snapshot, target_account, existing_body, mapping,
            quote_currencies, import_activities, update_balance, now=now, journal=journal)


def synchronize_locked(config, snapshot, target_account, existing_body, mapping,
                        quote_currencies, import_activities, update_balance, now=None, journal=None):
    """Validate whole account before mutation; accepted evidence alone funds sells."""
    dry_run = config.get("dry_run", True)
    if type(dry_run) is not bool:
        raise RuntimeError("Invalid DRY_RUN flag")
    if config.get("sync_mode", "full_history") not in ("full_history", "prospective"):
        raise RuntimeError("Invalid synchronization mode")
    check_api_import_format(snapshot)
    source = broker_identity(config.get("source_account"))
    if broker_identity(snapshot.get("source_account")) != source:
        raise RuntimeError("DEGIRO configured source account mismatch")
    if not isinstance(target_account, dict) or target_account.get("id") != config.get("target_account"):
        raise RuntimeError("Ghostfolio configured target account mismatch")
    if not core.activity_is_active({"account": target_account}) or target_account.get("balance") is None:
        raise RuntimeError("Ghostfolio target account excluded or redacted")
    prospective = config.get("sync_mode", "full_history") == "prospective"
    context = None
    if prospective:
        snapshot, existing, quantities, context = prospective_snapshot(
            config, snapshot, target_account, existing_body, mapping, quote_currencies)
    else:
        existing, quantities = existing_activity_context(existing_body, target_account)
    balance = current_cash_balance(snapshot, target_account, source, now)
    if prospective:
        activities = context["activities"]
    else:
        activities = normalize_trades(snapshot, target_account["id"], mapping, quote_currencies)
        activities += normalize_dividends(snapshot, target_account["id"], mapping, quote_currencies)
        activities += normalize_fees(snapshot, target_account["id"])
        activities += normalize_cash_yield(snapshot, target_account["id"])
    if any(not core.activity_date_is_current(activity) for activity in activities):
        raise RuntimeError("Future DEGIRO candidate blocks synchronization")
    pending = pending_activities(activities, existing, target_account, source)
    trades = [activity for activity in pending if activity["type"] in ("BUY", "SELL")]
    reconcile_trade_holdings(trades, existing, quantities)
    if not dry_run and not prospective and snapshot.get("history_completeness_verified") is not True:
        raise RuntimeError("Unverified DEGIRO history completeness blocks live writes")
    if target_account["id"] in config.get("_uncertain_import_accounts", set()):
        raise RuntimeError("Uncertain prior import blocks account writes")
    if dry_run:
        return {"proposed": pending, "accepted": [], "cash": balance, "dry_run": True,
                "history_verified": snapshot.get("history_completeness_verified") is True,
                "prospective_verified": prospective,
                "cutover": context["cutover"].isoformat() if context else None,
                "basis_status": context["basis_status"] if context else None}
    accepted = []
    for sells in (False, True):
        batch = [activity for activity in pending if (activity["type"] == "SELL") == sells]
        if not batch:
            continue
        if sells:
            reconcile_trade_holdings(batch, [], quantities)
        try:
            intent = begin_intent(journal, "import", {a["comment"]: a for a in batch})
            created, ok = import_activities(batch)
            if (ok is not True or not isinstance(created, list)
                    or len(created) != len(batch)
                    or {activity_signature(a) for a in created} != {activity_signature(a) for a in batch}):
                raise RuntimeError("Incomplete accepted account import evidence")
            confirm_intent(journal, intent)
        except Exception:
            core.mark_import_uncertain(config, batch)
            raise RuntimeError("Account import uncertain or incomplete; cash blocked") from None
        for activity in created:
            if activity["type"] in ("BUY", "SELL"):
                key = (activity["accountId"], activity["symbol"])
                quantities[key] = quantities.get(key, Decimal(0)) + financial_decimal(activity["quantity"]) * (
                    1 if activity["type"] == "BUY" else -1)
        accepted.extend(created)
    def guarded_balance(account, amount):
        intent = begin_intent(journal, "cash", {"account": account, "balance": amount})
        try:
            if update_balance(account, amount) is not True:
                raise RuntimeError("Cash update rejected")
            confirm_intent(journal, intent)
        except Exception:
            raise RuntimeError("Uncertain cash update remains durably fenced") from None
        return True

    apply_cash_balance(snapshot, target_account, source, guarded_balance, dry_run=False,
        import_ok=True, uncertain=target_account["id"] in config.get("_uncertain_import_accounts", set()), now=now)
    return {"proposed": pending, "accepted": accepted, "cash": balance, "dry_run": False,
            "history_verified": not prospective, "prospective_verified": prospective,
            "cutover": context["cutover"].isoformat() if context else None,
            "basis_status": context["basis_status"] if context else None}


PROSPECTIVE_FAILURES = frozenset({
    "Prospective opening holdings mismatch",
    "Prospective account or mapping binding mismatch", "Unproved prospective opening capture interval",
    "Concurrent prospective destination opening event", "Concurrent prospective broker opening event",
    "Incomplete prospective opening evidence", "Incomplete prospective interval coverage",
    "Prospective statement coverage mismatch", "Incomplete prospective statement evidence",
    "Unverified prospective statement header", "Unverified prospective statement row",
    "Protected prospective legacy history changed", "Late or changed pre-cutover source event",
    "Future prospective source event", "Ambiguous prospective value-date boundary",
    "Unproved prospective execution cash relation", "Prospective cash execution missing from trade feed",
    "Unproved post-cutover destination activity", "Prospective broker holdings do not reconcile",
    "Prospective date precision cannot be represented by Ghostfolio",
    "Missing prospective evidence digest", "Unsafe prospective evidence file",
    "Changed prospective evidence file", "Unavailable prospective evidence file",
    "Invalid prospective manifest schema", "Malformed prospective evidence",
    "Unverified prospective destination holding currency", "Unverified prospective security holding",
    "Unverified prospective holding mapping", "Conflicting prospective holding identity",
    "Incomplete prospective account evidence", "Unresolved durable write intent blocks account writes",
    "Ambiguous prospective timestamp precision",
})


def evidence_digest(value):
    """Stable JSON evidence digest; reject non-finite or unrepresentable input."""
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError):
        raise RuntimeError("Invalid prospective evidence content") from None


def read_private_evidence(path, expected_digest):
    """Read bounded, owned regular evidence without following a final symlink."""
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise RuntimeError("Missing prospective evidence digest")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 2_000_000):
            raise RuntimeError("Unsafe prospective evidence file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read(2_000_001)
        if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != expected_digest:
            raise RuntimeError("Changed prospective evidence file")
        return content
    except (OSError, TypeError):
        raise RuntimeError("Unavailable prospective evidence file") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def unique_evidence_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("Duplicate prospective evidence key")
        result[key] = value
    return result


def load_prospective_evidence(path, expected_digest):
    """An operator-pinned YAML manifest binds two unchanged private JSON captures."""
    try:
        content = read_private_evidence(path, expected_digest)
        # Inspect mapping nodes before safe_load: duplicate keys are never last-wins.
        root = yaml.compose(content)
        pending, visited = [root], set()
        while pending:
            node = pending.pop()
            if node is None or id(node) in visited:
                raise RuntimeError("Aliased prospective manifest is unsupported")
            visited.add(id(node))
            if isinstance(node, yaml.MappingNode):
                keys = [key.value for key, unused in node.value]
                if len(keys) != len(set(keys)):
                    raise RuntimeError("Duplicate prospective evidence key")
                pending.extend(item for pair in node.value for item in pair)
            elif isinstance(node, yaml.SequenceNode):
                pending.extend(node.value)
        manifest = yaml.safe_load(content)
        if (not isinstance(manifest, dict) or set(manifest) != {
                "version", "source_account", "target_account", "cutover",
                "mapping_sha256", "opening", "basis_status"}
                or type(manifest["version"]) is not int or manifest["version"] != 1
                or manifest["basis_status"] != "unverified"
                or set(manifest["opening"]) != {"broker", "destination"}):
            raise RuntimeError("Invalid prospective manifest schema")
        captures = {}
        for name, binding in manifest["opening"].items():
            if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
                raise RuntimeError("Invalid prospective capture binding")
            location = Path(binding["path"])
            if not location.is_absolute():
                location = Path(path).parent / location
            captures[name] = json.loads(read_private_evidence(location, binding["sha256"]),
                object_pairs_hook=unique_evidence_pairs,
                parse_constant=lambda unused: (_ for _ in ()).throw(
                    RuntimeError("Non-finite prospective evidence")))
        return {"manifest": manifest, "captures": captures,
                "manifest_sha256": expected_digest}
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError, yaml.YAMLError):
        raise RuntimeError("Malformed prospective evidence") from None


def broker_stock_holdings(snapshot, target_account, mapping, quote_currencies):
    """Decode every held security; missing metadata, units or instruments block."""
    quantities, identities = {}, set()
    for row in cash_wrapper_rows(snapshot["update"], "portfolio"):
        fields = named_values(row["value"])
        identity = row.get("id")
        if identity in identities or fields.get("id") != identity:
            raise RuntimeError("Conflicting prospective holding identity")
        identities.add(identity)
        size = financial_decimal(fields.get("size"))
        if isinstance(identity, str) and identity.startswith("FLATEX_"):
            continue  # Independently checked by current_cash_balance.
        if (identity in CASH_CURRENCIES
                and fields.get("positionType") == "CASH" and size == 0):
            continue  # Empty currency placeholders are not held securities.
        product_id = broker_identity(identity)
        if size == 0:
            continue
        product = snapshot["products"].get(product_id)
        if (not isinstance(product, dict) or broker_identity(product.get("id")) != product_id
                or product.get("productType") != "STOCK"
                or financial_decimal(product.get("contractSize")) != 1 or size < 0
                or not valid_isin(product.get("isin"))):
            raise RuntimeError("Unverified prospective security holding")
        symbol = mapping.get(product["isin"])
        if (not isinstance(symbol, str) or not symbol.strip()
                or quote_currencies.get(symbol) != product.get("currency")):
            raise RuntimeError("Unverified prospective holding mapping")
        key = (target_account["id"], symbol)
        quantities[key] = quantities.get(key, Decimal(0)) + size
    return {key: value for key, value in quantities.items() if value != 0}


def nonzero_holdings(quantities):
    return {key: value for key, value in quantities.items() if value != 0}


def prospective_instant(value):
    """Require explicit seconds and offset; never manufacture missing precision."""
    if (not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value)):
        raise RuntimeError("Ambiguous prospective timestamp precision")
    return datetime.fromisoformat(broker_instant(value))


def prospective_opening_context(evidence, config, mapping, quote_currencies):
    """Verify unchanged opening inventory without manufacturing destination rows."""
    try:
        manifest, captures = evidence["manifest"], evidence["captures"]
        if (manifest["source_account"] != broker_identity(config["source_account"])
                or manifest["target_account"] != config["target_account"]
                or manifest["mapping_sha256"] != evidence_digest({
                    "mapping": mapping, "quote_currencies": quote_currencies})
                or len(set(mapping.values())) != len(mapping)):
            raise RuntimeError("Prospective account or mapping binding mismatch")
        opening = captures["broker"]
        destination = captures["destination"]
        target = destination["account"]
        cutover = prospective_instant(manifest["cutover"])
        started = prospective_instant(opening["fetch_started_at"])
        fetched = prospective_instant(opening["fetched_at"])
        captured = prospective_instant(destination["captured_at"])
        if (cutover != fetched or not started <= captured <= fetched
                or fetched - started > timedelta(minutes=5)
                or target["id"] != config["target_account"]):
            raise RuntimeError("Unproved prospective opening capture interval")
        cash = current_cash_balance(opening, target, config["source_account"], now=fetched)
        financial_decimal(target["balance"])  # Existing cash may be stale; broker cash is authoritative.
        rows, quantities = existing_activity_context(destination["activities"], target)
        protected = {}
        for row in rows:
            if row["accountId"] != target["id"]:
                continue
            instant = datetime.fromisoformat(broker_instant(row["date"]))
            if instant > started:
                raise RuntimeError("Concurrent prospective destination opening event")
            if row["type"] in ("BUY", "SELL") and row["currency"] != quote_currencies.get(row["symbol"]):
                raise RuntimeError("Unverified prospective destination holding currency")
            protected[row["id"]] = evidence_digest({
                "signature": [str(value) for value in activity_signature(row)],
                "id": row["id"]})
        for row in opening["transactions"] + opening["cash_movements"]:
            if prospective_instant(row["date"]) > started:
                raise RuntimeError("Concurrent prospective broker opening event")
        if nonzero_holdings(quantities) != broker_stock_holdings(
                opening, target, mapping, quote_currencies):
            raise RuntimeError("Prospective opening holdings mismatch")
        return {"cutover": cutover, "opening": opening, "protected": protected,
                "quantities": quantities, "cash": cash, "basis_status": "unverified"}
    except (KeyError, TypeError, AttributeError, ValueError):
        raise RuntimeError("Incomplete prospective opening evidence") from None


def prospective_statement_matches(snapshot):
    """Exact raw cash multiset corroboration; no inference from CSV minute proximity."""
    header = ["Date", "Heure", "Date de", "Produit", "Code ISIN", "Description",
              "FX", "Mouvements", "", "Solde", "", "ID Ordre"]
    try:
        text = snapshot["account_report_csv"]
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or rows[0] != header:
            raise RuntimeError("Unverified prospective statement header")
        statement = []
        for row in rows[1:]:
            if len(row) != 12:
                raise RuntimeError("Unverified prospective statement row")
            datetime.strptime(row[0], "%d-%m-%Y")
            datetime.strptime(row[1], "%H:%M")
            datetime.strptime(row[2], "%d-%m-%Y")
            statement.append((row[0], row[1], row[2], row[4], row[5], row[7],
                financial_decimal(row[8].replace(",", ".")) if row[8] else None, row[11]))
        source = []
        for row in snapshot["cash_movements"]:
            instant = datetime.fromisoformat(broker_instant(row["date"]))
            # Preserve the broker offset for the separately corroborated statement clock.
            local = datetime.fromisoformat(row["date"])
            value = datetime.fromisoformat(broker_instant(row["valueDate"]))
            local_value = datetime.fromisoformat(row["valueDate"])
            product = snapshot["products"].get(str(row.get("productId")), {})
            source.append((local.strftime("%d-%m-%Y"), local.strftime("%H:%M"),
                local_value.strftime("%d-%m-%Y"), product.get("isin", ""), row["description"],
                row.get("currency", "") if row.get("change") is not None else "",
                financial_decimal(row["change"]) if row.get("change") is not None else None,
                str(row.get("orderId") or "")))
        if Counter(source) != Counter(statement):
            raise RuntimeError("Prospective statement coverage mismatch")
        return len(source)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Incomplete prospective statement evidence") from None


def prospective_execution_cash(snapshot):
    """Both feeds must expose each execution once with exact signed trade cash."""
    ledger = classify_cash_movements(snapshot["cash_movements"])["executed_trade_cash"]
    remaining = list(ledger)
    for trade in snapshot["transactions"]:
        product = snapshot["products"][broker_identity(trade["productId"])]
        candidates = [row for row in remaining
            if broker_identity(row.get("productId")) == broker_identity(trade["productId"])
            and broker_instant(row["date"]) == broker_instant(trade["date"])
            and row["currency"] == product["currency"]
            and financial_decimal(row["change"]) == financial_decimal(trade["total"])
            and row["description"].startswith("Achat " if trade["buysell"] == "B" else "Vente ")
            and (trade.get("orderId") is None or row.get("orderId") == trade["orderId"])]
        if len(candidates) != 1:
            raise RuntimeError("Unproved prospective execution cash relation")
        remaining.remove(candidates[0])
    if remaining:
        raise RuntimeError("Prospective cash execution missing from trade feed")


def prospective_snapshot(config, snapshot, target, existing_body, mapping, quotes):
    """Reconcile a full interval from a fixed cutover; never relabel full history."""
    try:
        evidence = load_prospective_evidence(config["cutover_manifest"], config["cutover_sha256"])
        context = prospective_opening_context(evidence, config, mapping, quotes)
        cutover, opening = context["cutover"], context["opening"]
        if (broker_identity(snapshot["source_account"]) != broker_identity(config["source_account"])
                or target["id"] != config["target_account"]):
            raise RuntimeError("Prospective source or target mismatch")
        fetched = prospective_instant(snapshot["fetched_at"])
        # Full replay since cutover deliberately avoids a mutable coverage checkpoint.
        boundary = cutover.astimezone(ZoneInfo("Europe/Zurich")).date()
        if (snapshot["from_date"] != opening["from_date"]
                or date.fromisoformat(snapshot["to_date"]) < fetched.astimezone(ZoneInfo("Europe/Zurich")).date()
                or date.fromisoformat(opening["from_date"]) > boundary
                or date.fromisoformat(opening["to_date"]) < boundary or fetched < cutover):
            raise RuntimeError("Incomplete prospective interval coverage")
        check_api_import_format(snapshot)
        snapshot = dict(snapshot)
        for collection in ("transactions", "cash_movements"):
            unique = []
            merge_history(unique, snapshot[collection], cash=collection == "cash_movements")
            snapshot[collection] = unique
        prospective_statement_matches(snapshot)
        rows, destination_quantities = existing_activity_context(existing_body, target)
        protected = context["protected"]
        present = {}
        prospective_existing = []
        for row in rows:
            if row["accountId"] != target["id"]:
                prospective_existing.append(row)
                continue
            if datetime.fromisoformat(broker_instant(row["date"])) <= cutover:
                present[row["id"]] = evidence_digest({
                    "signature": [str(value) for value in activity_signature(row)], "id": row["id"]})
            else:
                prospective_existing.append(row)
        if present != protected:
            raise RuntimeError("Protected prospective legacy history changed")
        result = dict(snapshot)
        result["history_completeness_verified"] = False
        for collection in ("transactions", "cash_movements"):
            before = opening[collection]
            actual = [row for row in snapshot[collection]
                if prospective_instant(row["date"]) <= cutover]
            def signatures(items):
                return Counter(evidence_digest({key: value for key, value in row.items()
                    if collection != "cash_movements" or key != "balance"}) for row in items)
            if signatures(before) != signatures(actual):
                raise RuntimeError("Late or changed pre-cutover source event")
            result[collection] = [row for row in snapshot[collection]
                if prospective_instant(row["date"]) > cutover]
            for row in result[collection]:
                instant = prospective_instant(row["date"])
                if instant > fetched:
                    raise RuntimeError("Future prospective source event")
                if collection == "cash_movements" and row.get("change") is not None:
                    value = prospective_instant(row["valueDate"])
                    if value <= cutover or value > fetched:
                        raise RuntimeError("Ambiguous prospective value-date boundary")
        prospective_execution_cash(result)
        activities = normalize_trades(result, target["id"], mapping, quotes)
        activities += normalize_dividends(result, target["id"], mapping, quotes)
        activities += normalize_fees(result, target["id"])
        activities += normalize_cash_yield(result, target["id"])
        if any(datetime.fromisoformat(activity["date"]).microsecond % 1000 for activity in activities):
            raise RuntimeError("Prospective date precision cannot be represented by Ghostfolio")
        # Every existing post-cutover target row must be evidenced by this full replay.
        pending_activities(activities, prospective_existing, target, config["source_account"])
        known = {row["comment"]: activity_signature(row) for row in activities}
        for row in prospective_existing:
            if row["accountId"] == target["id"] and (
                    row.get("comment") not in known or known[row["comment"]] != activity_signature(row)):
                raise RuntimeError("Unproved post-cutover destination activity")
        expected = dict(context["quantities"])
        for activity in activities:
            if activity["type"] in ("BUY", "SELL"):
                key = (target["id"], activity["symbol"])
                expected[key] = expected.get(key, Decimal(0)) + financial_decimal(activity["quantity"]) * (
                    1 if activity["type"] == "BUY" else -1)
        if nonzero_holdings(expected) != broker_stock_holdings(snapshot, target, mapping, quotes):
            raise RuntimeError("Prospective broker holdings do not reconcile")
        context["activities"] = activities
        result["prospective_verified"] = True
        return result, prospective_existing, destination_quantities, context
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Incomplete prospective account evidence") from None


def verified_mapping_document(document):
    """One mapping contract shared by runtime and offline cutover preparation."""
    try:
        if not isinstance(document, dict) or not document:
            raise ValueError
        mapping, quotes = {}, {}
        for isin, entry in document.items():
            if (not valid_isin(isin) or not isinstance(entry, dict)
                    or set(entry) != {"symbol", "currency"}
                    or not isinstance(entry["symbol"], str) or not entry["symbol"].strip()
                    or entry["symbol"] != entry["symbol"].strip()
                    or entry["currency"] not in CURRENCY_QUANTA):
                raise ValueError
            symbol, currency = entry["symbol"], entry["currency"]
            if symbol in quotes and quotes[symbol] != currency:
                raise ValueError
            mapping[isin], quotes[symbol] = symbol, currency
        return mapping, quotes
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("Invalid explicitly verified Yahoo mapping file") from None


def load_sync_config():
    """Operator configuration only; credentials are read verbatim from environment."""
    sync_mode = os.environ.get("SYNC_MODE", "full_history")
    if sync_mode not in ("full_history", "prospective"):
        raise RuntimeError("Invalid synchronization mode")
    host = validate_ghost_host(os.environ.get("GHOST_HOST"))
    token = os.environ.get("GHOST_TOKEN")
    target = os.environ.get("GHOST_ACCOUNT_ID")
    source = broker_identity(os.environ.get("DEGIRO_ACCOUNT_ID"))
    mode = os.environ.get("DRY_RUN", "1").strip().lower()
    if (not isinstance(token, str) or not token.strip() or "\r" in token or "\n" in token
            or not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", target)
            or mode not in ("1", "true", "yes", "on", "0", "false", "no", "off")):
        raise RuntimeError("Invalid Ghostfolio sync environment")
    try:
        document = yaml.safe_load(Path(os.environ.get("MAPPING_FILE", "mapping.yaml")).read_text())
        mapping, quotes = verified_mapping_document(document)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise RuntimeError("Invalid explicitly verified Yahoo mapping file") from None
    return {"ghost_host": host, "ghost_token": token, "source_account": source,
            "target_account": target, "dry_run": mode in ("1", "true", "yes", "on"),
            "state_dir": os.environ.get("STATE_DIR"), "sync_mode": sync_mode,
            "cutover_manifest": os.environ.get("CUTOVER_MANIFEST"),
            "cutover_sha256": os.environ.get("CUTOVER_SHA256")}, mapping, quotes


def run_sync(from_date, to_date, window_days=90):
    """One broker read and complete target read; no completeness assertion invented."""
    config, mapping, quotes = load_sync_config()
    if config["dry_run"] and config.get("sync_mode") != "prospective":
        return run_sync_locked(config, mapping, quotes, from_date, to_date, window_days)
    with account_journal(config) as journal:
        if journal["document"]["pending"] is not None:
            raise RuntimeError("Unresolved durable write intent blocks account writes")
        return run_sync_locked(config, mapping, quotes, from_date, to_date, window_days, journal)


def run_sync_locked(config, mapping, quotes, from_date, to_date, window_days, journal=None):
    """Live lock covers source/target reads as well as dispatch."""
    if config.get("sync_mode") == "prospective":
        evidence = load_prospective_evidence(config["cutover_manifest"], config["cutover_sha256"])
        context = prospective_opening_context(evidence, config, mapping, quotes)
        from_date = date.fromisoformat(context["opening"]["from_date"])
        to_date = max(to_date, datetime.now(ZoneInfo("Europe/Zurich")).date())
        snapshot = read_degiro(from_date, to_date, window_days,
            report_locale=("fr", "fr"), holdings=True)
    else:
        snapshot = read_degiro(from_date, to_date, window_days)
    expected_target = {"id": config["target_account"], "currency": snapshot["account_info"]["baseCurrency"]}
    with ghost_transport(config, expected_target) as session:
        response = session.get(f"{config['ghost_host']}/api/v1/account/{config['target_account']}")
        response.raise_for_status()
        target = response.json()
        response = session.get(f"{config['ghost_host']}/api/v1/activities")
        response.raise_for_status()
        existing = response.json()
        return synchronize_locked(config, snapshot, target, existing, mapping, quotes,
            lambda activities: core.ghost_import_activities(config, activities),
            lambda account, balance: core.ghost_update_cash_balance(config, account, balance), journal=journal)


def broker_credentials():
    """Construct the connector model exclusively from the process environment."""
    from degiro_connector.trading.models.credentials import Credentials
    values = [os.environ.get(name) for name in
              ("DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET")]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise RuntimeError("Missing DEGIRO credential environment variables")
    try:
        return Credentials(username=values[0], password=values[1], totp_secret_key=values[2])
    except Exception:
        raise RuntimeError("Invalid DEGIRO credentials") from None


@contextmanager
def private_broker_logs():
    """Mute broker and HTTP diagnostics during secret-bearing operations."""
    names = {"degiro_connector", "urllib3", "requests", "charset_normalizer"}
    names.update(name for name in logging.root.manager.loggerDict
                 if name.startswith(("degiro_connector.", "urllib3.", "requests.", "charset_normalizer.")))
    saved = []
    for name in names:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level, logger.disabled, logger.propagate))
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True
        logger.propagate = False
    try:
        yield
    finally:
        for logger, level, disabled, propagate in saved:
            logger.setLevel(level)
            logger.disabled = disabled
            logger.propagate = propagate


def quiet_broker_logger():
    logger = logging.Logger("degiro_adapter.silent")
    logger.disabled = True
    logger.propagate = False
    return logger


def bounded_broker_session():
    """No retries, redirects or order endpoints; reject maintenance before scraping."""
    from degiro_connector.core.constants.headers import HEADERS
    session = requests.Session()
    session.headers.update(HEADERS)
    session.trust_env = False
    session.degiro_diagnostics = {}
    original_send = session.send

    def send(request, **kwargs):
        parts = urlsplit(request.url)
        paths = BROKER_PATHS.get(request.method, ())
        if (parts.scheme != "https" or parts.netloc != "trader.degiro.nl"
                or parts.fragment or not any(re.fullmatch(path, parts.path) for path in paths)):
            raise RuntimeError("DEGIRO request outside read-only boundary")
        kwargs.update(timeout=BROKER_TIMEOUT, allow_redirects=False, verify=True, stream=False)
        try:
            response = original_send(request, **kwargs)
        except Exception as error:
            session.degiro_diagnostics["auth_reason"] = (
                "timeout" if isinstance(error, requests.Timeout) else
                "tls_error" if isinstance(error, requests.exceptions.SSLError) else "transport_error")
            raise RuntimeError("DEGIRO transport failed") from None
        if parts.path == "/login/secure/login/totp":
            code = response.status_code
            reason = {400: "http_400", 401: "http_401", 403: "http_403", 429: "http_429",
                      405: "maintenance"}.get(code, "http_5xx" if 500 <= code < 600 else
                                             "invalid_login_response")
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                if payload.get("captchaRequired") is True:
                    reason = "captcha_required"
                elif payload.get("status") == 6:
                    reason = "totp_required"
                elif payload.get("status") == 12:
                    reason = "in_app_required"
                elif code != 200 and isinstance(payload.get("status"), int):
                    reason = "broker_rejected"
            if 300 <= code < 400:
                reason = "redirect_refused"
            session.degiro_diagnostics["auth_reason"] = reason
        # Upstream login HTTP405 calls an unbounded HTML maintenance scraper.
        if response.status_code == 405 or 300 <= response.status_code < 400:
            raise RuntimeError("DEGIRO maintenance or redirect refused")
        if parts.path == "/portfolio-reports/secure/v3/cashAccountReport/csv":
            try:
                response.content.decode("utf-8-sig")
            except UnicodeError:
                raise RuntimeError("DEGIRO CSV is not valid UTF-8") from None
            # The real export omits charset; requests otherwise selects Latin-1.
            response.encoding = "utf-8-sig"
        return response

    session.send = send
    return session


def broker_call(action, **kwargs):
    try:
        result = action(**kwargs)
    except Exception:
        raise RuntimeError(f"DEGIRO {action.__name__} failed") from None
    if result is None:
        raise RuntimeError(f"DEGIRO {action.__name__} returned no data")
    return result


def history_windows(from_date, to_date, window_days=90):
    """Overlap one boundary day; this does not assert server completeness."""
    if (type(from_date) is not date or type(to_date) is not date or from_date > to_date
            or type(window_days) is not int or not 2 <= window_days <= 366):
        raise RuntimeError("Invalid DEGIRO history date range")
    result = []
    start = from_date
    while True:
        end = min(start + timedelta(days=window_days - 1), to_date)
        result.append((start, end))
        if len(result) > MAX_HISTORY_WINDOWS:
            raise RuntimeError("DEGIRO history range exceeds request budget")
        if end == to_date:
            return result
        start = end


def raw_rows(envelope, collection=None):
    if not isinstance(envelope, dict) or "data" not in envelope:
        raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    rows = envelope["data"]
    if collection:
        # Observed accountoverview response for an empty recent interval.
        # Prospective acceptance still requires exact statement corroboration.
        if collection == "cashMovements" and rows == {}:
            return []
        if not isinstance(rows, dict) or collection not in rows:
            raise RuntimeError(API_FORMAT_ERRORS["unknown"])
        rows = rows[collection]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    return rows


def merge_history(existing, rows, require_ids=True, cash=False, identity_field="id"):
    """Keep equal overlap rows once; reject missing identities or conflicting content."""
    for row in rows:
        if cash and row.get("type") in ("CASH_FUND_NAV_CHANGE", "CASH_FUND_TRANSACTION"):
            raise RuntimeError(API_FORMAT_ERRORS["legacy_cash"])
        identity = row.get(identity_field)
        if (isinstance(identity, bool) or not isinstance(identity, (str, int))
                or not str(identity).strip()):
            if require_ids:
                raise RuntimeError("DEGIRO history row has no stable identity")
            existing.append(row)
            continue
        matched = [item for item in existing if str(item.get(identity_field)) == str(identity)]
        if matched:
            first = {key: value for key, value in matched[0].items() if not cash or key != "balance"}
            second = {key: value for key, value in row.items() if not cash or key != "balance"}
            if first != second:
                raise RuntimeError("Conflicting DEGIRO overlap identity")
        else:
            existing.append(row)
    return existing


def history_product_ids(rows):
    result = set()
    for row in rows:
        value = row.get("productId")
        if value is None:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, str))
                or not re.fullmatch(r"[0-9]+", str(value)) or int(value) <= 0):
            raise RuntimeError("Invalid DEGIRO product identity")
        result.add(int(value))
    return sorted(result)


def read_degiro(from_date, to_date, window_days=90, report_locale=None, orders=False, holdings=False,
                cutover_target_reader=None):
    """Fetch raw private data with one login and guaranteed bounded logout attempt."""
    from degiro_connector.trading.actions.action_connect import ActionConnect
    from degiro_connector.trading.actions.action_get_client_details import ActionGetClientDetails
    from degiro_connector.trading.actions.action_get_transactions_history import ActionGetTransactionsHistory
    from degiro_connector.trading.actions.action_get_orders_history import ActionGetOrdersHistory
    from degiro_connector.trading.actions.action_get_account_overview import ActionGetAccountOverview
    from degiro_connector.trading.actions.action_get_products_info import ActionGetProductsInfo
    from degiro_connector.trading.actions.action_get_account_info import ActionGetAccountInfo
    from degiro_connector.trading.actions.action_get_account_report import ActionGetAccountReport
    from degiro_connector.trading.actions.action_get_update import ActionGetUpdate
    from degiro_connector.trading.actions.action_logout import ActionLogout
    from degiro_connector.trading.models.account import OverviewRequest, ReportRequest, UpdateOption, UpdateRequest
    from degiro_connector.trading.models.transaction import HistoryRequest
    from degiro_connector.trading.models.order import HistoryRequest as OrderHistoryRequest

    windows = history_windows(from_date, to_date, window_days)
    if report_locale is not None and (
            not isinstance(report_locale, tuple) or len(report_locale) != 2
            or any(not isinstance(part, str) or not re.fullmatch(r"[a-z]{2}", part)
                   for part in report_locale)):
        raise RuntimeError("Invalid DEGIRO report locale")
    credentials = broker_credentials()
    logger = quiet_broker_logger()
    session = bounded_broker_session()
    session_id = None
    failure = None
    data = {"transactions": [], "cash_movements": [], "products": {}, "orders": [],
            "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
            "fetch_started_at": datetime.now(timezone.utc).isoformat(),
            "history_completeness_verified": False}
    with private_broker_logs():
        stage = "login"
        try:
            session_id = broker_call(ActionConnect.get_session_id, credentials=credentials,
                                     session=session, logger=logger)
            if not isinstance(session_id, str) or not session_id.strip():
                raise RuntimeError("DEGIRO login has no usable session")
            shared = {"session_id": session_id, "session": session, "logger": logger}
            stage = "client_discovery"
            client = broker_call(ActionGetClientDetails.get_client_details, **shared)
            account = client.get("data", {}).get("intAccount") if isinstance(client, dict) and isinstance(client.get("data"), dict) else None
            if type(account) is not int or account <= 0:
                raise RuntimeError("DEGIRO client response has no valid intAccount")
            credentials.int_account = account
            data["source_account"] = str(account)
            shared["credentials"] = credentials
            for start, end in windows:
                stage = "transactions"
                transactions = broker_call(ActionGetTransactionsHistory.get_transactions_history,
                    transaction_request=HistoryRequest(from_date=start, to_date=end,
                                                       group_transactions_by_order=False),
                    raw=True, **shared)
                merge_history(data["transactions"], raw_rows(transactions))
                stage = "account_overview"
                overview = broker_call(ActionGetAccountOverview.get_account_overview,
                    overview_request=OverviewRequest(from_date=start, to_date=end), raw=True, **shared)
                merge_history(data["cash_movements"], raw_rows(overview, "cashMovements"),
                              require_ids=len(windows) > 1, cash=True)
                if orders:
                    stage = "order_history"
                    history = broker_call(ActionGetOrdersHistory.get_orders_history,
                        history_request=OrderHistoryRequest(from_date=start, to_date=end),
                        raw=True, **shared)
                    merge_history(data["orders"], raw_rows(history), identity_field="orderId")
            stage = "products"
            ids = history_product_ids(data["transactions"] + data["cash_movements"])
            for offset in range(0, len(ids), 100):
                products = broker_call(ActionGetProductsInfo.get_products_info,
                                      product_list=ids[offset:offset + 100], raw=True, **shared)
                if (not isinstance(products, dict) or not isinstance(products.get("data"), dict)
                        or any(not isinstance(row, dict) for row in products["data"].values())):
                    raise RuntimeError("Invalid DEGIRO product response")
                for identity in ids[offset:offset + 100]:
                    if str(identity) not in products["data"]:
                        raise RuntimeError("Missing DEGIRO product metadata")
                data["products"].update(products["data"])
            stage = "account_info"
            account_info = broker_call(ActionGetAccountInfo.get_account_info, **shared)
            if not isinstance(account_info, dict) or not isinstance(account_info.get("data"), dict):
                raise RuntimeError("Invalid DEGIRO account info response")
            data["account_info"] = account_info["data"]
            stage = "account_update"
            update = broker_call(ActionGetUpdate.get_update, request_list=[
                UpdateRequest(option=option, last_updated=0) for option in
                (UpdateOption.PORTFOLIO, UpdateOption.TOTAL_PORTFOLIO, UpdateOption.CASH_FUNDS)],
                raw=True, **shared)
            if (not isinstance(update, dict) or not update
                    or any(not isinstance(update.get(key), dict) for key in
                           ("portfolio", "totalPortfolio", "cashFunds"))):
                raise RuntimeError("Invalid DEGIRO update response")
            data["update"] = update
            if holdings:
                held, identities = [], set()
                for row in cash_wrapper_rows(update, "portfolio"):
                    identity = row.get("id")
                    fields = named_values(row["value"])
                    if identity in identities or fields.get("id") != identity:
                        raise RuntimeError("Conflicting prospective holding identity")
                    identities.add(identity)
                    if isinstance(identity, str) and identity.startswith("FLATEX_"):
                        continue
                    if (identity in CASH_CURRENCIES
                            and fields.get("positionType") == "CASH"
                            and financial_decimal(fields.get("size")) == 0):
                        continue
                    product_id = broker_identity(identity)
                    if financial_decimal(fields.get("size")) == 0:
                        continue
                    held.append(int(product_id))
                missing = sorted(set(held) - {int(identity) for identity in data["products"]})
                stage = "products"
                for offset in range(0, len(missing), 100):
                    requested = missing[offset:offset + 100]
                    products = broker_call(ActionGetProductsInfo.get_products_info,
                        product_list=requested, raw=True, **shared)
                    if (not isinstance(products, dict) or not isinstance(products.get("data"), dict)
                            or any(not isinstance(products["data"].get(str(identity)), dict)
                                   for identity in requested)):
                        raise RuntimeError("Missing held DEGIRO product metadata")
                    data["products"].update(products["data"])
            if report_locale:
                stage = "account_report"
                report = broker_call(ActionGetAccountReport.get_cash_account_report,
                    report_request=ReportRequest(country=report_locale[0], lang=report_locale[1],
                                                 from_date=from_date, to_date=to_date),
                    raw=True, **shared)
                if (not isinstance(report, str) or not report.strip()
                        or report.lstrip().startswith("<")):
                    raise RuntimeError("Invalid DEGIRO CSV report response")
                data["account_report_csv"] = report
            if cutover_target_reader is not None:
                stage = "cutover_destination"
                data["opening_destination"] = cutover_target_reader()
        except Exception as error:
            reason = getattr(session, "degiro_diagnostics", {}).get("auth_reason")
            if str(error) in API_FORMAT_ERRORS.values():
                failure = RuntimeError(str(error))
            elif stage == "login" and reason in AUTH_FAILURE_REASONS:
                failure = RuntimeError(f"DEGIRO login failed: {reason}")
            else:
                failure = RuntimeError(f"DEGIRO read failed at {stage}; no financial writes attempted")
        finally:
            if session_id:
                try:
                    ok = broker_call(ActionLogout.logout, credentials=credentials,
                                     session_id=session_id, session=session, logger=logger)
                    if ok is not True:
                        raise RuntimeError("DEGIRO logout failed")
                except Exception:
                    failure = failure or RuntimeError("DEGIRO logout failed")
            session.close()
    if failure:
        raise failure from None
    data["fetched_at"] = datetime.now(timezone.utc).isoformat()
    check_api_import_format(data)
    return data


def redact_auth_fields(value):
    """Private financial snapshots must still exclude incidental auth fields."""
    if isinstance(value, dict):
        return {key: redact_auth_fields(item) for key, item in value.items()
                if not any(part in key.lower() for part in
                           ("token", "session", "password", "username", "otp", "secret"))}
    if isinstance(value, list):
        return [redact_auth_fields(item) for item in value]
    return value


def snapshot_destination(destination):
    root = Path(__file__).resolve().parent
    destination = Path(destination).resolve()
    if root in destination.parents and root / "tmp" not in destination.parents:
        raise RuntimeError("Private snapshot must be outside Git or under ignored tmp/")
    if destination.exists():
        raise FileExistsError("Private snapshot already exists")
    return destination


def save_private_snapshot(data, destination):
    destination = snapshot_destination(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(redact_auth_fields(data), indent=2, allow_nan=False).encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def main(argv=None):
    """Explicit operator modes; normal sync defaults to DRY_RUN and fails closed."""
    if not argv:
        log.error("DEGIRO sync gates incomplete; use explicit --read-only characterization")
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--read-only", action="store_true")
    modes.add_argument("--sync", action="store_true")
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--output")
    parser.add_argument("--report-country")
    parser.add_argument("--report-language")
    parser.add_argument("--orders", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.sync:
            if args.output or args.report_country or args.report_language or args.orders:
                raise RuntimeError("Read-only options cannot be used for synchronization")
            end = date.fromisoformat(args.to_date or datetime.now(timezone.utc).date().isoformat())
            lookback = int(os.environ.get("LOOKBACK_DAYS", "90"))
            if not 2 <= lookback <= 366:
                raise RuntimeError("Invalid bounded history lookback")
            start = date.fromisoformat(args.from_date) if args.from_date else end - timedelta(days=lookback - 1)
            result = run_sync(start, end, args.window_days)
            log.info("Sync %s: %d proposed activities, %d accepted", "DRY_RUN" if result["dry_run"] else "live",
                     len(result["proposed"]), len(result["accepted"]))
            if result["dry_run"] and result.get("prospective_verified") is True:
                log.info("Proposed Ghostfolio cash balance: EUR %.2f; DRY_RUN, no update sent", result["cash"])
            if result.get("prospective_verified") is True:
                log.info("Prospective contract verified; historical completeness and basis remain unverified")
                return 0
            if not result["history_verified"]:
                log.warning("History completeness is unverified; live writes remain blocked")
                return 1
            return 0
        if not args.output or not args.from_date or not args.to_date:
            raise RuntimeError("Read-only snapshot requires dates and an output path")
        output = snapshot_destination(args.output)
        locale = None
        if args.report_country or args.report_language:
            locale = (args.report_country, args.report_language)
        data = read_degiro(date.fromisoformat(args.from_date), date.fromisoformat(args.to_date),
                           args.window_days, report_locale=locale, orders=args.orders)
        save_private_snapshot(data, output)
    except Exception as error:
        if args.sync:
            message = str(error)
            log.error("%s", message if message in API_FORMAT_ERRORS.values() or message in PROSPECTIVE_FAILURES else
                      "DEGIRO sync failed; unknown, incomplete or uncertain account state blocks writes")
            return 1
        stages = ("login", "client_discovery", "transactions", "account_overview", "products",
                  "account_info", "account_update", "account_report", "order_history", "cutover_destination")
        messages = {f"DEGIRO read failed at {stage}; no financial writes attempted" for stage in stages}
        messages.add("DEGIRO logout failed")
        messages.update(API_FORMAT_ERRORS.values())
        messages.update(f"DEGIRO login failed: {reason}" for reason in AUTH_FAILURE_REASONS)
        message = str(error)
        log.error("%s", message if message in messages else
                  "DEGIRO read-only characterization failed; no financial writes attempted")
        return 1
    log.info("Read-only snapshot saved: %d transactions, %d cash movements",
             len(data["transactions"]), len(data["cash_movements"]))
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main(sys.argv[1:]))
