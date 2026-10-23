"""Connector command orchestration and private snapshot output."""

import argparse
import io
import json
import logging
import os
import re
from contextlib import redirect_stderr
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ghostfolio_degiro_sync import accounting as accounting_module
from ghostfolio_degiro_sync import config as config_module
from ghostfolio_degiro_sync import degiro as degiro_module
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import ghostfolio as ghostfolio_module
from ghostfolio_degiro_sync import notify as notify_module
from ghostfolio_degiro_sync import sync as sync_module

log = logging.getLogger(__name__)

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


def redact_auth_fields(value: Any) -> Any:
    """Private financial snapshots must still exclude incidental auth fields."""
    if isinstance(value, dict):
        return {key: redact_auth_fields(item) for key, item in value.items()
                if not any(part in key.lower() for part in
                           ("token", "session", "password", "username", "otp", "secret"))}
    if isinstance(value, list):
        return [redact_auth_fields(item) for item in value]
    return value


def snapshot_destination(destination: Any) -> Any:
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    if root in destination.parents and root / "tmp" not in destination.parents:
        raise RuntimeError("Private snapshot must be outside Git or under ignored tmp/")
    if destination.exists():
        raise FileExistsError("Private snapshot already exists")
    return destination


def save_private_snapshot(data: Any, destination: Any, compact: Any=False) -> Any:
    destination = snapshot_destination(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(redact_auth_fields(data), indent=None if compact else 2,
        separators=(",", ":") if compact else None, allow_nan=False).encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def simulation_plan(result: Any, start: Any, end: Any) -> Any:
    """Publish only the financial proposal and its verification context."""
    period = result.get("period") or {}
    return {"generated_at": datetime.now(UTC).isoformat(),
            "version": os.environ.get("APP_VERSION", "dev"),
            "period": {"from_date": period.get("from_date") or start.isoformat(),
                       "to_date": period.get("to_date") or end.isoformat(), "timezone": "Europe/Zurich"},
            "activities": result["proposed"], "cash": result.get("cash"),
            "cash_before": result.get("cash_before"), "cash_currency": "EUR",
            "candidates": result.get("candidates"), "exclusions": result.get("exclusions", {}),
            "history_verified": result["history_verified"],
            "rolling_verified": result.get("rolling_verified", False),
            "prospective_verified": result.get("prospective_verified", False)}


def log_simulation(result: Any) -> Any:
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
    for line in diagnostics_module.render_reconciliation(result.get("reconciliation", [])).splitlines():
        log.info("%s", line)
    exclusions = result.get("exclusions", {})
    log.info("[DRY RUN] Candidate exclusions: already_imported=%d manual_match=%d duplicate_candidate=%d",
             exclusions.get("already_imported", 0), exclusions.get("manual_match", 0),
             exclusions.get("duplicate_candidate", 0))



def _main(argv: Any=None, failures: Any=None) -> Any:
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
                if os.environ.get("DRY_RUN", "").strip().lower() not in ("", "1", "true", "yes", "on"):
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
                history_error = diagnostics_module.tag_failure(RuntimeError("History completeness is unverified"),
                                    "sync", "reconciliation")
                if failures is not None:
                    failures.append(history_error)
                diagnostics_module.log_failure("History verification failed", history_error)
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
        if failures is not None:
            failures.append(error)
        if args.sync:
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


def main(argv: Any=None) -> Any:
    """Resolve simulation policy before access and finalize one outcome."""
    if not os.environ.get("DRY_RUN", "").strip():
        log.warning("DRY_RUN not set: simulation, nothing written")
    try:
        config_module.configure_logging(os.environ)
        unused_dry_run, forced = config_module.simulation_policy(os.environ)
    except RuntimeError as error:
        diagnostics_module.log_failure("Invalid synchronization configuration", error)
        notify_module.finalize_failure(error)
        return 1
    if not config_module.valid_timezone(os.environ.get("TZ")):
        log.warning("Missing or invalid TZ: simulation forced, nothing written")
    failures: list[Exception] = []
    status = _main(argv, failures)
    if status:
        notify_module.finalize_failure(failures[0] if failures else RuntimeError("sync_failed"))
    elif forced and argv and "--sync" in argv:
        notify_module.finalize_forced_preview()
    return status
