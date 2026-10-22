#!/usr/bin/env python3
"""Read-only DEGIRO adapter; activity writes require the remaining validation gates."""

import argparse
import base64
import csv
import fcntl
import hashlib
import io
import json
import logging
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from contextlib import contextmanager, redirect_stderr
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
import yaml

if sys.argv[1:] != ["--notify-worker"]:
    import ghostfolio_core as core
    from ghostfolio_degiro_sync import accounting as accounting_module
    from ghostfolio_degiro_sync import degiro as degiro_module
    from ghostfolio_degiro_sync import diagnostics as diagnostics_module
    from ghostfolio_degiro_sync import ghostfolio as ghostfolio_module
    from ghostfolio_degiro_sync import sync as sync_module
    from ghostfolio_degiro_sync.accounting import (
        API_FORMAT_ERRORS,
        CASH_CURRENCIES,
        CURRENCY_QUANTA,
        TRADE_FIELDS,
        activity_signature,
        apply_cash_balance,
        associate_dividends,
        broker_instant,
        cash_wrapper_rows,
        check_api_import_format,
        classify_cash_movements,
        convert_trade_to_activity,
        current_cash_balance,
        financial_decimal,
        load_cash_rules,
        merge_history,
        named_values,
        normalize_cash_yield,
        normalize_dividends,
        normalize_fees,
        normalize_trades,
        prospective_instant,
        reconcile_execution_costs,
        reconcile_trade_holdings,
        trade_signature,
        valid_isin,
        validate_cash_yield,
        validate_cash_yield_identity,
    )
    from ghostfolio_degiro_sync.config import (
        load_ghost_credentials,
        load_sync_config,
        optional_string,
        parse_settings,
        required_string,
        runtime_config,
        validate_ghost_host,
        verified_mapping_document,
    )
    from ghostfolio_degiro_sync.degiro import (
        BROKER_PATHS,
        BROKER_TIMEOUT,
        MAX_HISTORY_WINDOWS,
        bounded_broker_session,
        broker_call,
        history_product_ids,
        history_windows,
        quiet_broker_logger,
        raw_rows,
        read_degiro,
    )
    from ghostfolio_degiro_sync.diagnostics import (
        AUTH_FAILURE_REASONS,
        BROKER_READ_STAGES,
        FAILURE_DIAGNOSTICS,
        diagnostic_boundary,
        failure_diagnostic,
        log_failure,
        private_broker_logs,
        tag_failure,
    )
    from ghostfolio_degiro_sync.ghostfolio import (
        _HEADER_SAFE_TOKEN_RE,
        GHOST_AUTH_TIMEOUT,
        authenticate_ghostfolio,
        cleanup_preflight,
        discover_ghost_accounts,
        existing_activity_context,
        ghost_exchange_access_token,
        ghost_transport,
        match_manual_activity,
        pending_activities,
        warn_ghost_http,
    )
    from ghostfolio_degiro_sync.identity import (
        broker_identity,
        execution_comment,
        parse_legacy_identity,
    )
    from ghostfolio_degiro_sync.journal import (
        account_journal,
        begin_intent,
        confirm_intent,
        evidence_digest,
        load_prospective_evidence,
        private_state_file,
        read_private_evidence,
        readback_import_intent,
        recover_confirmed_import,
        resolve_import_intent,
        selected_import_intent,
        unique_evidence_pairs,
        verify_import_intent,
        write_journal,
    )
    from ghostfolio_degiro_sync.sync import (
        broker_stock_holdings,
        execution_cash_matches,
        nonzero_holdings,
        prospective_execution_cash,
        prospective_opening_context,
        prospective_snapshot,
        prospective_statement_matches,
        rolling_snapshot,
        run_sync,
        run_sync_locked,
        synchronize_account,
        synchronize_locked,
    )
    from ghostfolio_degiro_sync.vault import (
        broker_credentials,
        vault_broker_credentials,
    )


log = logging.getLogger(__name__)


# Deliberately limited to the characterized major currencies. Minor quotes
# require separate broker evidence; an IBKR suffix rule is not DEGIRO evidence.


# Adapted from ghostfolio-ibkr-sync 54958ab1035eb97a1f67f9072b79699813ec3800;
# deliberately outside the immutable projection. See docs/ghostfolio-auth.md.


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


ROLLING_FAILURES = frozenset({
    "Rolling mode requires 90 days through broker-local today",
    "Rolling mode requires LOOKBACK_DAYS=90",
    "Rolling coverage gap requires explicit catch-up start",
    "Incomplete rolling interval coverage", "Rolling source event outside verified interval",
    "Future rolling cash value date", "Incomplete rolling account evidence",
    "Rolling broker holdings do not reconcile", "Unproved rolling destination activity",
    "Rolling date precision cannot be represented by Ghostfolio",
    "Invalid rolling coverage state", "Ambiguous nearby manual trade quantity",
    "Complete exact positive readback required for recovery",
})


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


def save_private_snapshot(data, destination, compact=False):
    destination = snapshot_destination(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(redact_auth_fields(data), indent=None if compact else 2,
        separators=(",", ":") if compact else None, allow_nan=False).encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def simulation_plan(result, start, end):
    """Publish only the financial proposal and its verification context."""
    period = result.get("period") or {}
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "version": os.environ.get("APP_VERSION", "dev"),
            "period": {"from_date": period.get("from_date") or start.isoformat(),
                       "to_date": period.get("to_date") or end.isoformat(), "timezone": "Europe/Zurich"},
            "activities": result["proposed"], "cash": result.get("cash"),
            "cash_before": result.get("cash_before"), "cash_currency": "EUR",
            "candidates": result.get("candidates"), "exclusions": result.get("exclusions", {}),
            "history_verified": result["history_verified"],
            "rolling_verified": result.get("rolling_verified", False),
            "prospective_verified": result.get("prospective_verified", False)}


def log_simulation(result):
    """Financial review fields only; never dump raw responses or provenance comments."""
    for activity in result["proposed"]:
        # Custom fee/yield symbols embed the source account; retain the category only.
        symbol = re.sub(r"^GF_DEGIRO_[1-9][0-9]*_", "GF_DEGIRO_", activity.get("symbol") or "")
        # Quote text to prevent broker or mapping values from injecting log lines.
        log.info("[DRY RUN] %s %s %s qty=%s price=%s %s fee=%s",
                 json.dumps(activity.get("date")), json.dumps(activity.get("type")),
                 json.dumps(symbol), activity.get("quantity"),
                 activity.get("unitPrice"), activity.get("currency"), activity.get("fee"))
    if result.get("cash_before") is not None and result.get("cash") is not None:
        log.info("[DRY RUN] Ghostfolio cash: EUR %.2f -> %.2f (no update sent)",
                 result["cash_before"], result["cash"])
    elif result.get("cash") is not None:
        log.info("[DRY RUN] Proposed Ghostfolio cash: EUR %.2f (no update sent)", result["cash"])
    exclusions = result.get("exclusions", {})
    log.info("[DRY RUN] Candidate exclusions: already_imported=%d manual_match=%d duplicate_candidate=%d",
             exclusions.get("already_imported", 0), exclusions.get("manual_match", 0),
             exclusions.get("duplicate_candidate", 0))


NOTIFY_WORKER_FLAG = "--notify-worker"
NOTIFY_PAYLOAD_MAX = 32 * 1024
APPRISE_URLS_MAX = 10
APPRISE_URL_MAX_LEN = 2048
APPRISE_TIMEOUT_DEFAULT = 10
APPRISE_TIMEOUT_MAX = 30
# The worker inherits only what Apprise needs to reach a destination: never the
# DEGIRO or Ghostfolio credentials.
NOTIFY_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
                        "REQUESTS_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                        "http_proxy", "https_proxy", "no_proxy")
# Worker exit code -> delivery status reported by send_notification.  Kept clear
# of the interpreter's own codes (1 uncaught error, 2 cannot open the script).
NOTIFY_EXIT_STATUS = {0: "sent", 10: "invalid_payload", 11: "unavailable", 12: "failed",
                      13: "invalid_destination"}


def load_notification_config():
    """Parse APPRISE_URLS and APPRISE_TIMEOUT; None means notifications are off.

    APPRISE_URLS is a JSON list of Apprise URL strings (blank or [] = off);
    APPRISE_TIMEOUT an integer number of seconds, 1..30 (default 10).  Never
    raises: invalid settings only disable delivery, with a fixed warning since
    the values carry destination credentials.
    """
    raw = os.environ.get("APPRISE_URLS", "")
    if not raw.strip():
        return None
    try:
        urls = json.loads(raw) if len(raw) <= NOTIFY_PAYLOAD_MAX else None
    except ValueError:
        urls = None
    raw_timeout = os.environ.get("APPRISE_TIMEOUT", "").strip()
    timeout = APPRISE_TIMEOUT_DEFAULT
    if raw_timeout:
        timeout = int(raw_timeout) if re.fullmatch(r"[0-9]{1,2}", raw_timeout) else 0
    if (not isinstance(urls, list) or len(urls) > APPRISE_URLS_MAX
            or not all(isinstance(u, str) and u.strip() and len(u) <= APPRISE_URL_MAX_LEN
                       for u in urls)
            or not 1 <= timeout <= APPRISE_TIMEOUT_MAX):
        log.warning("APPRISE_URLS or APPRISE_TIMEOUT is invalid: failure notifications disabled")
        return None
    if not urls:
        return None
    return {"urls": urls, "timeout": timeout}


def notify_worker():
    """Worker process entry: deliver one notification read from stdin.

    Never runs the sync.  Apprise is imported here only, so the sync never
    loads it.  Exit codes: see NOTIFY_EXIT_STATUS.
    """
    logging.disable(logging.CRITICAL)
    raw = sys.stdin.buffer.read(NOTIFY_PAYLOAD_MAX + 1)
    try:
        payload = json.loads(raw) if len(raw) <= NOTIFY_PAYLOAD_MAX else None
    except ValueError:
        payload = None
    if (not isinstance(payload, dict)
            or not isinstance(payload.get("urls"), list) or not payload["urls"]
            or not all(isinstance(u, str) for u in payload["urls"])
            or not isinstance(payload.get("title"), str)
            or not isinstance(payload.get("body"), str)):
        return 10
    try:
        import apprise
    except ImportError:
        return 11
    notifier = apprise.Apprise()
    # One entry may hold several space- or comma-separated URLs: bound the
    # destinations Apprise actually expanded, not the list entries
    if (not all(notifier.add(url) for url in payload["urls"])
            or len(notifier) > APPRISE_URLS_MAX):
        return 13
    try:
        sent = notifier.notify(title=payload["title"], body=payload["body"])
    except Exception:
        return 12
    return 0 if sent else 12


def _notify_worker_argv():
    # -I: ignore PYTHON* variables, user site-packages and the current directory
    return [sys.executable, "-I", os.path.abspath(__file__), NOTIFY_WORKER_FLAG]


def _stop_worker(proc):
    """Kill the worker (and anything it started) if still running, then reap it."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    proc.wait()


def send_notification(settings, title, body):
    """Deliver one notification through an isolated Apprise worker.

    Apprise plugins can block past any library timeout and can print their
    destination URL.  So the URLs travel on stdin, the worker gets an
    allowlisted environment and no output channel, and one deadline covers its
    whole life (import, setup, send, exit); on expiry it is killed and reaped.
    No retry: a timed-out send may still have been delivered.  Returns a fixed
    status string; SystemExit/KeyboardInterrupt propagate after the kill.
    """
    payload = json.dumps({"urls": settings["urls"], "title": title, "body": body}).encode()
    if len(payload) > NOTIFY_PAYLOAD_MAX:
        return "payload_too_large"
    # The worker re-runs this file: impossible when the script came from stdin
    if not os.path.isfile(os.path.abspath(__file__)):
        return "spawn_failed"
    env = {k: os.environ[k] for k in NOTIFY_ENV_ALLOWLIST if k in os.environ}
    try:
        proc = subprocess.Popen(_notify_worker_argv(), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=env, close_fds=True, start_new_session=True)
    except (OSError, ValueError):
        return "spawn_failed"
    try:
        proc.communicate(payload, timeout=settings["timeout"])
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception:
        return "failed"
    finally:
        _stop_worker(proc)
    return NOTIFY_EXIT_STATUS.get(proc.returncode, "failed")


NOTIFY_TITLE = "ghostfolio-degiro-sync: run failed"
NOTIFY_REASONS = {
    "Rolling coverage gap requires explicit catch-up start": "coverage_gap: rerun with an explicit earlier --from-date",
    "Complete exact positive readback required for recovery": "import_uncertain: inspect persisted import intent",
    "Unresolved durable write intent blocks account writes": "write_uncertain: inspect persisted write intent",
    "Existing DEGIRO identity changed financial evidence": "activity_conflict: compare source and destination",
    "Rolling broker holdings do not reconcile": "holdings_mismatch: compare source and destination",
    "Ambiguous nearby manual trade quantity": "manual_trade_ambiguous: compare quantities",
}


def finalize_failure(error):
    """One private alert for live failures or scheduled simulations."""
    live = os.environ.get("DRY_RUN", "1").strip().lower() in ("0", "false", "no", "off")
    if not live and not os.environ.get("CRON", "").strip():
        return
    try:
        settings = load_notification_config()
        if settings is None:
            return
        reason = NOTIFY_REASONS.get(str(error), "sync_failed: inspect container log")
        body = ("Run failed at " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC.")
                + "\n" + reason + "\nDetails are in the container log.")
        status = send_notification(settings, NOTIFY_TITLE, body)
        if status == "sent":
            log.info("Failure notification sent")
        else:
            log.warning("Failure notification not delivered: %s", status)
    except Exception:
        log.warning("Failure notification could not be sent: internal error")


def main(argv=None):
    """Explicit operator modes; normal sync defaults to DRY_RUN and fails closed."""
    if not argv:
        log.error("DEGIRO sync gates incomplete; use explicit --read-only characterization; stage=config reason=mode")
        return 1
    parser = argparse.ArgumentParser(prog="degiro-sync", description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--read-only", action="store_true")
    modes.add_argument("--sync", action="store_true")
    modes.add_argument("--ghost-accounts", action="store_true")
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--output")
    parser.add_argument("--plan-output", help="New private JSON proposal file; DRY_RUN sync only")
    parser.add_argument("--report-country")
    parser.add_argument("--report-language")
    parser.add_argument("--orders", action="store_true")
    # argparse normally echoes invalid values, including accidentally pasted keys.
    # Keep its error output private; --help still prints the static help to stdout.
    try:
        with redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code == 0:
            return 0
        log.error("Invalid command arguments; stage=config reason=arguments; use --help")
        return 2
    try:
        if not 2 <= args.window_days <= 366:
            raise diagnostics_module.tag_failure(RuntimeError("Invalid broker query window"), "config", "window_days")
        if args.ghost_accounts:
            if (not args.output or args.plan_output or args.from_date or args.to_date
                    or args.report_country or args.report_language or args.orders):
                raise diagnostics_module.tag_failure(RuntimeError("Account discovery requires only an output path"),
                                  "config", "arguments")
            with diagnostics_module.diagnostic_boundary("output", "destination"):
                output = snapshot_destination(args.output)
            with diagnostics_module.diagnostic_boundary("ghostfolio", "account_read"):
                data = ghostfolio_module.discover_ghost_accounts()
            with diagnostics_module.diagnostic_boundary("output", "write"):
                save_private_snapshot(data, output)
            log.info("Private Ghostfolio account identifiers saved")
            return 0
        if args.sync:
            if args.output or args.report_country or args.report_language or args.orders:
                raise diagnostics_module.tag_failure(RuntimeError("Read-only options cannot be used for synchronization"),
                                  "config", "arguments")
            plan_output = None
            if args.plan_output:
                if os.environ.get("DRY_RUN", "1").strip().lower() not in ("1", "true", "yes", "on"):
                    raise diagnostics_module.tag_failure(RuntimeError("Proposal output requires DRY_RUN"),
                                      "config", "arguments")
                with diagnostics_module.diagnostic_boundary("output", "destination"):
                    plan_output = snapshot_destination(args.plan_output)
            with diagnostics_module.diagnostic_boundary("config", "date_range"):
                end = date.fromisoformat(args.to_date or datetime.now(ZoneInfo("Europe/Zurich")).date().isoformat())
            with diagnostics_module.diagnostic_boundary("config", "lookback_days"):
                lookback = int(os.environ.get("LOOKBACK_DAYS", "90"))
                if not 2 <= lookback <= 366:
                    raise RuntimeError("Invalid bounded history lookback")
                if os.environ.get("SYNC_MODE") == "rolling" and lookback != 90:
                    raise RuntimeError("Rolling mode requires LOOKBACK_DAYS=90")
            with diagnostics_module.diagnostic_boundary("config", "date_range"):
                start = date.fromisoformat(args.from_date) if args.from_date else end - timedelta(days=lookback - 1)
                degiro_module.history_windows(start, end, args.window_days)
            with diagnostics_module.diagnostic_boundary("sync", "reconciliation"):
                result = sync_module.run_sync(start, end, args.window_days)
            if plan_output is not None:
                if result.get("dry_run") is not True or result.get("accepted"):
                    raise RuntimeError("Proposal output requires a financial simulation")
                plan = simulation_plan(result, start, end)
                with diagnostics_module.diagnostic_boundary("output", "write"):
                    save_private_snapshot(plan, plan_output)
                log.info("Private simulation plan saved; no financial writes sent")
            log.info("Sync %s: %d proposed activities, %d accepted", "DRY_RUN" if result["dry_run"] else "live",
                     len(result["proposed"]), len(result["accepted"]))
            if result["dry_run"]:
                log_simulation(result)
            if result.get("rolling_verified") is True:
                log.info("Rolling 90-day contract verified; historical completeness and basis remain unverified")
                return 0
            if result.get("prospective_verified") is True:
                log.info("Prospective contract verified; historical completeness and basis remain unverified")
                return 0
            if not result["history_verified"]:
                log.warning("History completeness is unverified; live writes remain blocked")
                error = diagnostics_module.tag_failure(RuntimeError("History completeness is unverified"),
                                    "sync", "reconciliation")
                diagnostics_module.log_failure("History verification failed", error)
                finalize_failure(error)
                return 1
            return 0
        if args.plan_output or not args.output or not args.from_date or not args.to_date:
            raise diagnostics_module.tag_failure(RuntimeError("Read-only snapshot requires dates and an output path"),
                              "config", "arguments")
        with diagnostics_module.diagnostic_boundary("output", "destination"):
            output = snapshot_destination(args.output)
        locale = None
        if args.report_country or args.report_language:
            locale = (args.report_country, args.report_language)
        with diagnostics_module.diagnostic_boundary("config", "date_range"):
            start, end = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
            degiro_module.history_windows(start, end, args.window_days)
        with diagnostics_module.diagnostic_boundary("broker", "read"):
            data = degiro_module.read_degiro(start, end, args.window_days, report_locale=locale, orders=args.orders)
        with diagnostics_module.diagnostic_boundary("output", "write"):
            save_private_snapshot(data, output)
    except Exception as error:
        if args.sync:
            finalize_failure(error)
            message = str(error)
            diagnostics_module.log_failure(message if message in accounting_module.API_FORMAT_ERRORS.values() or message in PROSPECTIVE_FAILURES
                        or message in ROLLING_FAILURES else
                        "DEGIRO sync failed; unknown, incomplete or uncertain account state blocks writes", error)
            return 1
        messages = {f"DEGIRO read failed at {stage}; no financial writes attempted" for stage in diagnostics_module.BROKER_READ_STAGES}
        messages.add("DEGIRO logout failed")
        messages.update(accounting_module.API_FORMAT_ERRORS.values())
        messages.update(f"DEGIRO login failed: {reason}" for reason in diagnostics_module.AUTH_FAILURE_REASONS)
        message = str(error)
        diagnostics_module.log_failure(message if message in messages else
                    "Ghostfolio account discovery failed; no financial writes attempted" if args.ghost_accounts else
                    "DEGIRO read-only characterization failed; no financial writes attempted", error,
                    fallback=("ghostfolio", "account_read") if args.ghost_accounts else ("broker", "read"))
        return 1
    log.info("Read-only snapshot saved: %d transactions, %d cash movements",
             len(data["transactions"]), len(data["cash_movements"]))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == [NOTIFY_WORKER_FLAG]:
        raise SystemExit(notify_worker())
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main(sys.argv[1:]))
