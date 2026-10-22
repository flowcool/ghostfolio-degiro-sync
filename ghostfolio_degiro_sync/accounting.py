"""Exact financial input validation."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from math import isfinite
from pathlib import Path
from typing import Any, TypeGuard, cast

import yaml

from ghostfolio_degiro_sync import identity as identity_module

# Observed placeholders only; nonzero cash in these currencies is not authorized.
CASH_CURRENCIES = frozenset({"CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "USD"})

CURRENCY_QUANTA = {"EUR": Decimal("0.01"), "USD": Decimal("0.01"), "JPY": Decimal("1")}


TRADE_FIELDS = ("accountId", "comment", "currency", "dataSource", "date", "fee",
                "quantity", "symbol", "type", "unitPrice")


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


def broker_instant(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise RuntimeError("DEGIRO timestamp requires an explicit offset")
    return parsed.astimezone(UTC).isoformat()


def valid_isin(value: object) -> TypeGuard[str]:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        return False
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def convert_trade_to_activity(trade: Any, product: Any, source_account: Any, target_account: str,
                              base_currency: Any, mapping: dict[str, str], quote_currencies: dict[str, str]) -> Any:
    """Normalize one execution; no ticker fallback, unit inference or fee clamping."""
    if not isinstance(trade, dict) or not isinstance(product, dict):
        raise RuntimeError("Invalid DEGIRO execution metadata")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    comment = identity_module.execution_comment(source_account, trade.get("id"))
    product_id = identity_module.broker_identity(trade.get("productId"))
    if identity_module.broker_identity(product.get("id")) != product_id:
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


def normalize_trades(snapshot: dict[str, Any], target_account: Any, mapping: dict[str, str], quote_currencies: dict[str, str]) -> list[dict[str, Any]]:
    """Keep individual fills and reject conflicting duplicate execution identities."""
    rows: list[dict[str, Any]] = []
    merge_history(rows, snapshot["transactions"])
    result: list[dict[str, Any]] = []
    for trade in rows:
        product_id = identity_module.broker_identity(trade.get("productId"))
        product = snapshot["products"].get(product_id)
        result.append(convert_trade_to_activity(trade, product, snapshot["source_account"],
            target_account, snapshot["account_info"]["baseCurrency"], mapping, quote_currencies))
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def trade_signature(activity: dict[str, Any]) -> tuple[Any, ...]:
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


def reconcile_trade_holdings(activities: Any, existing: Any, quantities: Any) -> list[dict[str, Any]]:
    """Pure account/symbol guard; manual overlap needs explicit reconciliation.

    Existing contains active target activities; quantities is the active holding
    baseline keyed by (target account, Yahoo symbol). Future orchestration owns
    the complete/redaction-checked read, never this pure function.
    """
    identities: dict[tuple[Any, Any], Any] = {}
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
    pending: list[dict[str, Any]] = []
    seen: dict[tuple[Any, Any], Any] = {}
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


def load_cash_rules(path: Any=None) -> Any:
    """Read the reviewed local taxonomy; malformed rules never broaden matching."""
    path = Path(path) if path is not None else files("ghostfolio_degiro_sync").joinpath("cash-rules.yaml")
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


def classify_cash_movements(rows: list[dict[str, Any]], rules: dict[str, Any] | None=None) -> dict[str, list[dict[str, Any]]]:
    """Classify the entire ledger; preserve row identity and reject ambiguity."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Invalid DEGIRO cash ledger")
    rules = load_cash_rules() if rules is None else rules
    unique: list[dict[str, Any]] = []
    merge_history(unique, rows, cash=True)
    result: dict[str, list[dict[str, Any]]] = {name: [] for name in rules}
    for row in unique:
        identity_module.broker_identity(row.get("id"))
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
            identity_module.broker_identity(row.get("productId"))
        if rule.get("order_required") and (
                not isinstance(row.get("orderId"), str) or not row["orderId"].strip()):
            raise RuntimeError("Missing DEGIRO cash order relation")
        result[name].append(row)
    return result


def validate_cash_yield(row: dict[str, Any], category: str, treatment: str | None) -> None:
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


def normalize_cash_yield(snapshot: dict[str, Any], target_account: Any, rules: Any=None) -> list[dict[str, Any]]:
    """Retain zero interest and distinct compensation receipts without cash effects."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    source = identity_module.broker_identity(snapshot["source_account"])
    result: list[dict[str, Any]] = []
    for category, kind, label in (("flatex_interest", "INTEREST", "FLATEX_INTEREST"),
                                 ("monetary_fund_compensation", "COMPENSATION", "MMF_COMPENSATION")):
        for row in classified.get(category, []):
            validate_cash_yield(row, category, rules[category].get("treatment"))
            if snapshot["account_info"]["baseCurrency"] != "EUR":
                raise RuntimeError("Unverified DEGIRO cash yield account currency")
            result.append({"accountId": target_account,
                "comment": f"DEGIRO#{source}:{kind}:{identity_module.broker_identity(row['id'])}",
                "currency": "EUR", "dataSource": "MANUAL", "date": broker_instant(row["date"]),
                "fee": 0, "quantity": 1, "symbol": f"GF_DEGIRO_{source}_{label}_EUR",
                "type": "INTEREST", "unitPrice": float(financial_decimal(row["change"]))})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def associate_dividends(classified: Any) -> Any:
    """One observed payment and one withholding per exact association group."""
    groups: dict[tuple[str, Any, Any, Any], dict[str, list[dict[str, Any]]]] = {}
    for category in ("paid_dividend", "dividend_withholding"):
        for row in classified.get(category, []):
            if row.get("orderId") not in (None, ""):
                raise RuntimeError("Unverified DEGIRO dividend relation")
            key = (identity_module.broker_identity(row.get("productId")), row["currency"],
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


def normalize_dividends(snapshot: dict[str, Any], target_account: Any, mapping: dict[str, str], quote_currencies: dict[str, str], rules: Any=None) -> list[dict[str, Any]]:
    """Import paid cash amounts independently of current or historical holdings."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    result: list[dict[str, Any]] = []
    for dividend, withholding in associate_dividends(classified):
        product_id = identity_module.broker_identity(dividend["productId"])
        product = snapshot["products"].get(product_id)
        if (not isinstance(product, dict) or identity_module.broker_identity(product.get("id")) != product_id
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
            "comment": f"DEGIRO#{identity_module.broker_identity(snapshot['source_account'])}:DIVIDEND:{identity_module.broker_identity(dividend['id'])}",
            "currency": currency, "dataSource": "YAHOO", "date": broker_instant(dividend["date"]),
            "fee": tax, "quantity": 1, "symbol": symbol, "type": "DIVIDEND", "unitPrice": gross})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def reconcile_execution_costs(classified: Any, transactions: Any, base_currency: Any) -> Any:
    """A brokerage ledger debit must evidence one already included execution fee."""
    executions: list[dict[str, Any]] = []
    merge_history(executions, transactions)
    matched = set()
    for row in classified.get("trade_commission", []):
        candidates = [trade for trade in executions
            if identity_module.broker_identity(trade.get("productId")) == identity_module.broker_identity(row["productId"])
            and broker_instant(trade.get("date")) == broker_instant(row["date"])]
        if len(candidates) != 1 or row["currency"] != base_currency:
            raise RuntimeError("Unverified or ambiguous DEGIRO execution cost")
        trade = candidates[0]
        identity = identity_module.broker_identity(trade.get("id"))
        brokerage = financial_decimal(trade.get("feeInBaseCurrency"))
        autofx = financial_decimal(trade.get("autoFxFeeInBaseCurrency"))
        total = financial_decimal(trade.get("totalFeesInBaseCurrency"))
        if (identity in matched or brokerage >= 0 or autofx > 0
                or total != brokerage + autofx or financial_decimal(row["change"]) != brokerage
                or (trade.get("orderId") is not None and trade["orderId"] != row["orderId"])):
            raise RuntimeError("DEGIRO execution cost does not reconcile")
        matched.add(identity)


def normalize_fees(snapshot: dict[str, Any], target_account: Any, rules: Any=None) -> list[dict[str, Any]]:
    """Only observed autonomous connection charges; no absolute-value refunds."""
    rules = load_cash_rules() if rules is None else rules
    classified = classify_cash_movements(snapshot["cash_movements"], rules)
    if any(classified[name] for name, rule in rules.items()
           if rule.get("treatment") == "unsupported_blocking"):
        raise RuntimeError("Unsupported DEGIRO cash category blocks account writes")
    if not isinstance(target_account, str) or not target_account.strip():
        raise RuntimeError("Missing Ghostfolio target account")
    source_account = identity_module.broker_identity(snapshot["source_account"])
    base_currency = snapshot["account_info"]["baseCurrency"]
    reconcile_execution_costs(classified, snapshot["transactions"], base_currency)
    result: list[dict[str, Any]] = []
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
                "comment": f"DEGIRO#{source_account}:FEE:{identity_module.broker_identity(row['id'])}",
                "currency": "EUR", "dataSource": "MANUAL", "date": broker_instant(row["date"]),
                "fee": fee, "quantity": 1,
                "symbol": f"GF_DEGIRO_{source_account}_EXCHANGE_CONNECTION_EUR",
                "type": "FEE", "unitPrice": 0})
    return sorted(result, key=lambda activity: (activity["date"], activity["comment"]))


def current_cash_balance(snapshot: dict[str, Any], target_account: Any, source_account: Any, now: Any=None) -> Any:
    """Validate the observed EUR current snapshot; aliases are cross-checks only."""
    now = datetime.now(UTC) if now is None else now
    try:
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise RuntimeError("Cash validation requires an aware current time")
        started = datetime.fromisoformat(broker_instant(snapshot["fetch_started_at"]))
        fetched = datetime.fromisoformat(broker_instant(snapshot["fetched_at"]))
        if not now - timedelta(minutes=5) <= started <= fetched <= now:
            raise RuntimeError("DEGIRO cash snapshot is stale or has invalid timing")
        if identity_module.broker_identity(snapshot["source_account"]) != identity_module.broker_identity(source_account):
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


def apply_cash_balance(snapshot: dict[str, Any], target_account: Any, source_account: Any, update_balance: Any,
                       dry_run: Any=True, import_ok: Any=False, uncertain: Any=False, now: Any=None) -> Any:
    """C11 binds the URL-validated writer; no callback runs without clean evidence."""
    if type(dry_run) is not bool or type(uncertain) is not bool or import_ok is not True or uncertain:
        raise RuntimeError("Ambiguous or unsuccessful account import blocks cash update")
    balance = current_cash_balance(snapshot, target_account, source_account, now)
    if not dry_run:
        if not callable(update_balance) or update_balance(target_account["id"], balance) is not True:
            raise RuntimeError("Ghostfolio cash update did not confirm success")
    return balance


def activity_signature(activity: dict[str, Any]) -> tuple[Any, ...]:
    """Exact normalized DTO evidence independent of server row/profile metadata."""
    try:
        values = dict(activity)
        values["date"] = broker_instant(values["date"])
        for field in ("quantity", "unitPrice", "fee"):
            values[field] = financial_decimal(values[field])
        return tuple(values[field] for field in TRADE_FIELDS)
    except (KeyError, TypeError):
        raise RuntimeError("Incomplete Ghostfolio activity evidence") from None


def validate_cash_yield_identity(activity: dict[str, Any], namespace: str) -> None:
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


def merge_history(existing: list[dict[str, Any]], rows: list[dict[str, Any]], require_ids: bool=True, cash: bool=False, identity_field: str="id") -> list[dict[str, Any]]:
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


def prospective_instant(value: Any) -> Any:
    """Require explicit seconds and offset; never manufacture missing precision."""
    if (not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value)):
        raise RuntimeError("Ambiguous prospective timestamp precision")
    return datetime.fromisoformat(broker_instant(value))
