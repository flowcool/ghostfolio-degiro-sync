"""Isolated, bounded and secret-free notification delivery."""

import json
import logging
import os
import re
import signal
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

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


def load_notification_config() -> Any:
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


def notify_worker() -> Any:
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


def _notify_worker_argv() -> Any:
    # -I: ignore PYTHON* variables, user site-packages and the current directory
    return [sys.executable, "-I", "-m", "ghostfolio_degiro_sync", NOTIFY_WORKER_FLAG]


def _stop_worker(proc: Any) -> Any:
    """Kill the worker (and anything it started) if still running, then reap it."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    proc.wait()


def send_notification(settings: Any, title: Any, body: Any) -> Any:
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
    # Refuse a missing notification module before starting the installed worker.
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


def finalize_failure(error: Any) -> Any:
    """One private alert for live failures or scheduled simulations."""
    try:
        settings = load_notification_config()
        if settings is None:
            return
        reason = NOTIFY_REASONS.get(str(error), "sync_failed: inspect container log")
        body = ("Run failed at " + datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC.")
                + "\n" + reason + "\nDetails are in the container log.")
        status = send_notification(settings, NOTIFY_TITLE, body)
        if status == "sent":
            log.info("Failure notification sent")
        else:
            log.warning("Failure notification not delivered: %s", status)
    except Exception:
        log.warning("Failure notification could not be sent: internal error")



def finalize_forced_preview() -> None:
    """A successful explicit-live request forced to simulation has one summary."""
    try:
        settings = load_notification_config()
        if settings is not None:
            status = send_notification(settings, "ghostfolio-degiro-sync: simulation forced",
                "Missing or invalid TZ forced simulation. No financial writes were sent.")
            if status != "sent":
                log.warning("Simulation notification not delivered: %s", status)
    except Exception:
        log.warning("Simulation notification could not be sent: internal error")
