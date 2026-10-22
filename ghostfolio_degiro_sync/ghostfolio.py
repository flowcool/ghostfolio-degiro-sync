"""Ghostfolio operations; explicit functional boundaries."""

import hashlib
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import requests

import ghostfolio_core as core
from ghostfolio_degiro_sync import accounting as accounting_module
from ghostfolio_degiro_sync import config as config_module
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import identity as identity_module

log=logging.getLogger(__name__)


def ghost_exchange_access_token(host: Any, access_token: Any) -> Any:
    """IBKR exchange contract with DEGIRO exact origin and private transport."""
    config_module.validate_ghost_host(host)
    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("Invalid Ghostfolio security token")
    warn_ghost_http(host)
    with diagnostics_module.private_broker_logs(), requests.Session() as session:
        session.trust_env = False
        try:
            response = session.post(f"{host}/api/v1/auth/anonymous",
                json={"accessToken": access_token}, timeout=GHOST_AUTH_TIMEOUT,
                allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError("Ghostfolio login failed: network error") from None
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Ghostfolio login failed: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("Ghostfolio login failed: response is not JSON") from None
        token = body.get("authToken") if isinstance(body, dict) else None
        if not isinstance(token, str) or not _HEADER_SAFE_TOKEN_RE.fullmatch(token):
            raise RuntimeError("Ghostfolio login failed: response has no usable authToken")
        return token


def authenticate_ghostfolio(config: Any) -> Any:
    """Resolve the security token once, discarding it from runtime config."""
    if "ghost_access_token" in config:
        with diagnostics_module.diagnostic_boundary("ghostfolio", "authentication"):
            config["ghost_token"] = ghost_exchange_access_token(
                config["ghost_host"], config.pop("ghost_access_token"))


def warn_ghost_http(host: Any) -> Any:
    """Fixed diagnostic only, after the caller validates the configured origin."""
    if urlsplit(host).scheme == "http":
        log.warning("Ghostfolio HTTP sends credentials in cleartext without server authentication; "
                    "single-label DNS does not guarantee a local destination. "
                    "Use HTTPS or an isolated trusted network")


@contextmanager
def ghost_transport(config: Any, target_account: Any) -> Iterator[Any]:
    """Bind immutable core to bounded HTTP for this sequential single-thread run."""
    host = config_module.validate_ghost_host(config.get("ghost_host"))
    token = config.get("ghost_token")
    dry_run = config.get("dry_run", True)
    if (not isinstance(token, str) or not token.strip() or "\r" in token or "\n" in token
            or type(dry_run) is not bool or not isinstance(target_account, dict)
            or not isinstance(target_account.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", target_account["id"])):
        raise RuntimeError("Invalid Ghostfolio transport configuration")
    warn_ghost_http(host)
    session: Any = requests.Session()
    session.trust_env = False
    session.headers.update(core.ghost_headers(token))
    session.RequestException = requests.RequestException
    original_send = session.send
    account_path = f"/api/v1/account/{target_account['id']}"

    def send(request: Any, **kwargs: Any) -> Any:
        parts = urlsplit(request.url)
        origin = f"{parts.scheme}://{parts.netloc}"
        allowed = (request.method == "GET" and parts.path in
                   ("/api/v1/account", "/api/v1/activities", account_path)) or (
                   not dry_run and request.method == "POST" and parts.path == "/api/v1/import") or (
                   not dry_run and request.method == "PUT" and parts.path == account_path)
        if origin != host or parts.query or parts.fragment or not allowed:
            raise RuntimeError("Ghostfolio request outside the approved sync boundary")
        read_timeout = (120 if request.method == "GET" and parts.path in ("/api/v1/account", account_path)
                        else 30 if request.method == "PUT" else 60)
        kwargs.update(timeout=(10, read_timeout), allow_redirects=False, verify=True, stream=False)
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
            accounting_module.financial_decimal(current["balance"])
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


def index_existing_activities(body: Any, target_account: Any, *, now: datetime | None=None) -> tuple[list[dict[str, Any]], dict[tuple[str, str], Decimal]]:
    """Complete unredacted list; never discard ownership or inactive target rows."""
    if not isinstance(body, dict) or not isinstance(body.get("activities"), list):
        raise RuntimeError("Invalid Ghostfolio activity list")
    now = datetime.now(UTC) if now is None else now
    rows = body["activities"]
    if type(body.get("count")) is not int or body["count"] != len(rows):
        raise RuntimeError("Incomplete Ghostfolio activity list")
    identities = set()
    result = []
    balances: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise RuntimeError("Invalid Ghostfolio created activity identity")
        if row["id"] in identities:
            raise RuntimeError("Duplicate Ghostfolio created activity identity")
        identities.add(row["id"])
        for field in ("quantity", "unitPrice", "fee"):
            if accounting_module.financial_decimal(row.get(field)) < 0:
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
        accounting_module.broker_instant(row.get("date"))
        if row.get("accountId") != target_account["id"]:
            result.append(normalized)
            continue
        if profile["dataSource"] not in ("YAHOO", "MANUAL"):
            raise RuntimeError("Unsupported target asset data source")
        if row.get("type") not in ("BUY", "SELL", "DIVIDEND", "FEE", "INTEREST"):
            raise RuntimeError("Unsupported target activity type blocks synchronization")
        if row.get("type") == "INTEREST" and (
                profile["dataSource"] != "MANUAL" or row.get("currency") != "EUR"
                or accounting_module.financial_decimal(row["quantity"]) != 1 or accounting_module.financial_decimal(row["fee"]) != 0):
            raise RuntimeError("Unverified target interest representation")
        if not core.activity_is_active(row) or not activity_date_is_current(row, now):
            raise RuntimeError("Inactive or future target activity blocks synchronization")
        if row.get("type") in ("BUY", "SELL"):
            if profile["dataSource"] != "YAHOO":
                raise RuntimeError("Unverified target holding data source")
            quantity = accounting_module.financial_decimal(row["quantity"])
            key = (row["accountId"], profile["symbol"])
            balances[key] = balances.get(key, Decimal(0)) + (quantity if row["type"] == "BUY" else -quantity)
        result.append(normalized)
    if any(quantity < 0 for quantity in balances.values()):
        raise RuntimeError("Negative existing target holding blocks synchronization")
    return result, balances


def match_manual_activity(activity: Any, entries: Any) -> Any:
    """IBKR's consumed nearest +/-2-day quantity match and +/-3-day dividend rule."""
    day = datetime.fromisoformat(accounting_module.broker_instant(activity["date"])).date()
    nearby = []
    limit = 3 if activity["type"] == "DIVIDEND" else 2
    for row in entries:
        if (row["accountId"], row["type"], row["symbol"]) != (
                activity["accountId"], activity["type"], activity["symbol"]):
            continue
        gap = abs((datetime.fromisoformat(accounting_module.broker_instant(row["date"])).date() - day).days)
        if gap <= limit:
            nearby.append((gap, row))
    if activity["type"] == "DIVIDEND":
        return bool(nearby)
    if activity["type"] not in ("BUY", "SELL"):
        return False
    matches = [item for item in nearby if abs(accounting_module.financial_decimal(item[1]["quantity"]) -
        accounting_module.financial_decimal(activity["quantity"])) < Decimal("0.001")]
    if matches:
        row = min(matches, key=lambda item: item[0])[1]
        entries.remove(row)
        return True
    if nearby:
        raise RuntimeError("Ambiguous nearby manual trade quantity")
    return False


def pending_activities(activities: Any, existing: Any, target_account: Any, source_account: Any, manual_matching: Any=False,
                       exclusions: Any=None) -> Any:
    """Canonical identities never fall back to proximity or another account."""
    namespace = f"DEGIRO#{identity_module.broker_identity(source_account)}:"
    known = {}
    for row in existing:
        comment = row.get("comment")
        if not isinstance(comment, str) or not comment.startswith(namespace):
            continue
        if row.get("accountId") != target_account["id"]:
            raise RuntimeError("DEGIRO identity is owned by another target account")
        if identity_module.parse_legacy_identity(comment) is None:
            raise RuntimeError("Malformed existing DEGIRO canonical identity")
        if comment in known:
            raise RuntimeError("Duplicate existing DEGIRO canonical identity")
        accounting_module.validate_cash_yield_identity(row, namespace)
        known[comment] = row
    result = []
    seen: dict[str, Any] = {}
    manual = [row for row in existing if not str(row.get("comment") or "").startswith("DEGIRO#")]
    ordered = sorted(activities, key=lambda row: (accounting_module.broker_instant(row["date"]), row["comment"])) if manual_matching else activities
    for activity in ordered:
        if activity.get("accountId") != target_account["id"]:
            raise RuntimeError("Candidate target account mismatch")
        comment = activity["comment"]
        accounting_module.validate_cash_yield_identity(activity, namespace)
        signature = accounting_module.activity_signature(activity)
        if comment in seen:
            if signature != seen[comment]:
                raise RuntimeError("Conflicting candidate DEGIRO identity")
            if exclusions is not None:
                exclusions["duplicate_candidate"] += 1
            continue
        seen[comment] = signature
        if comment in known:
            if signature != accounting_module.activity_signature(known[comment]):
                raise RuntimeError("Existing DEGIRO identity changed financial evidence")
            if exclusions is not None:
                exclusions["already_imported"] += 1
            continue
        if manual_matching and match_manual_activity(activity, manual):
            if exclusions is not None:
                exclusions["manual_match"] += 1
            continue
        for row in existing:
            if row.get("accountId") != target_account["id"] or row.get("type") != activity["type"]:
                continue
            old_comment = row.get("comment") or ""
            if old_comment.startswith("DEGIRO#"):
                continue
            gap = abs((datetime.fromisoformat(accounting_module.broker_instant(row["date"])).date()
                       - datetime.fromisoformat(activity["date"]).date()).days)
            if (gap <= 2 and (activity["type"] in ("FEE", "INTEREST") or row["symbol"] == activity["symbol"])):
                raise RuntimeError("Manual or CSV activity requires explicit reconciliation")
        result.append(activity)
    return result


def cleanup_preflight(existing_body: Any, manifest: Any) -> Any:
    """Select exact proved broker IDs only; never perform or authorize deletion."""
    if (not isinstance(manifest, dict) or set(manifest) != {"source_account", "target_account", "activities"}
            or not isinstance(manifest["activities"], dict) or not manifest["activities"]):
        raise RuntimeError("Invalid DEGIRO cleanup manifest")
    source = identity_module.broker_identity(manifest["source_account"])
    target = manifest["target_account"]
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise RuntimeError("Invalid cleanup target account")
    namespace = f"DEGIRO#{source}:"
    activities = list(manifest["activities"].values())
    for identity, activity in manifest["activities"].items():
        if (not isinstance(identity, str) or not isinstance(activity, dict) or set(activity) != set(accounting_module.TRADE_FIELDS)
                or activity.get("accountId") != target or activity.get("comment") != identity
                or not re.fullmatch(re.escape(namespace) + r"(TRADE|DIVIDEND|FEE|INTEREST|COMPENSATION):[1-9][0-9]*", identity)):
            raise RuntimeError("Unproved cleanup broker ownership")
        accounting_module.activity_signature(activity)
    rows, _ = existing_activity_context(existing_body, {"id": target})
    if pending_activities(activities, rows, {"id": target}, source):
        raise RuntimeError("Cleanup requires complete exact positive activity evidence")
    selected = {row["comment"]: row["id"] for row in rows
                if row.get("accountId") == target and row.get("comment") in manifest["activities"]}
    snapshot_hash = hashlib.sha256(json.dumps(existing_body, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"source_account": source, "target_account": target,
            "activity_ids": selected, "snapshot_sha256": snapshot_hash}


def discover_ghost_accounts() -> Any:
    """Read only account identifiers; keep balances and credentials out of output."""
    with diagnostics_module.diagnostic_boundary("config", "ghostfolio_credentials"):
        config = config_module.load_ghost_credentials()
    config["dry_run"] = True
    authenticate_ghostfolio(config)
    with diagnostics_module.private_broker_logs(), ghost_transport(config, {"id": "discovery"}) as session:
        response = session.get(f"{config['ghost_host']}/api/v1/account")
        response.raise_for_status()
        body = response.json()
    accounts = body.get("accounts") if isinstance(body, dict) else body
    if not isinstance(accounts, list):
        raise RuntimeError("Invalid Ghostfolio account discovery response")
    result, identities = [], set()
    for account in accounts:
        if (not isinstance(account, dict) or not isinstance(account.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]+", account["id"])
                or account["id"] in identities or not isinstance(account.get("name"), str)
                or not re.fullmatch(r"[A-Z]{3}", account.get("currency", ""))):
            raise RuntimeError("Invalid Ghostfolio account discovery response")
        identities.add(account["id"])
        result.append({key: account[key] for key in ("id", "name", "currency")})
    return {"accounts": result}


GHOST_AUTH_TIMEOUT = (10, 30)


_HEADER_SAFE_TOKEN_RE = re.compile(r"[\x21-\x7e]+")


def activity_date_is_current(activity: dict[str, Any], now: datetime) -> bool:
    """Validate against the supplied instant, never a second wall-clock read."""
    try:
        instant = datetime.fromisoformat(activity["date"].replace("Z", "+00:00"))
        return instant.tzinfo is not None and now.tzinfo is not None and instant <= now
    except (KeyError, TypeError, AttributeError, ValueError):
        return False


def record_accepted_activities(accepted: list[dict[str, Any]],
        holdings: dict[tuple[str, str], Decimal]) -> dict[tuple[str, str], Decimal]:
    """Project only proven accepted rows; leave the proposal state untouched."""
    result = dict(holdings)
    for activity in accepted:
        if activity["type"] in ("BUY", "SELL"):
            key = (activity["accountId"], activity["symbol"])
            result[key] = result.get(key, Decimal(0)) + accounting_module.financial_decimal(activity["quantity"]) * (
                1 if activity["type"] == "BUY" else -1)
    return result


# Transitional import for existing callers; both names share the pure index.
existing_activity_context = index_existing_activities
