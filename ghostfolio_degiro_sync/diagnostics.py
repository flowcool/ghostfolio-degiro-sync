"""Fixed public diagnostic boundaries and private library logging."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

AUTH_FAILURE_REASONS = ("transport_error", "timeout", "tls_error", "redirect_refused",
                        "maintenance", "captcha_required", "totp_required", "in_app_required",
                        "http_400", "http_401", "http_403", "http_429", "http_5xx",
                        "invalid_login_response", "broker_rejected")
BROKER_READ_STAGES = ("login", "client_discovery", "transactions", "account_overview",
                      "products", "account_info", "account_update", "account_report",
                      "order_history", "cutover_destination", "logout")
# Public diagnostic tokens are fixed; never derive them from external text.
FAILURE_DIAGNOSTICS = frozenset(
    [("config", reason) for reason in ("arguments", "mode", "date_range", "window_days",
        "lookback_days", "report_locale", "mapping", "state_dir", "account",
        "sync_mode", "ghostfolio_credentials", "direct_credentials", "broker_credentials")]
    + [("vault", reason) for reason in ("configuration", "temporary_state", "server",
        "login", "unlock", "sync", "item", "logout")]
    + [(stage, "failed") for stage in BROKER_READ_STAGES]
    + [("login", reason) for reason in AUTH_FAILURE_REASONS]
    + [("broker", "read"), ("broker", "api_format"), ("sync", "reconciliation"),
       ("sync", "failed"), ("output", "destination"), ("output", "write"),
       ("ghostfolio", "authentication"), ("ghostfolio", "transport"),
       ("ghostfolio", "account_read"), ("ghostfolio", "activities_read")])


def failure_diagnostic(error: Any) -> Any:
    """Revalidate even attached metadata before rendering it publicly."""
    value = getattr(error, "sync_diagnostic", None)
    if (type(value) is tuple and len(value) == 2
            and all(type(part) is str for part in value) and value in FAILURE_DIAGNOSTICS):
        return value
    return None


def tag_failure(error: Any, stage: Any, reason: Any) -> Any:
    """Keep the earliest known boundary while leaving exception semantics intact."""
    if failure_diagnostic(error) is None and (stage, reason) in FAILURE_DIAGNOSTICS:
        error.sync_diagnostic = (stage, reason)
    return error


@contextmanager
def diagnostic_boundary(stage: Any, reason: Any) -> Iterator[None]:
    try:
        yield
    except Exception as error:
        tag_failure(error, stage, reason)
        raise


def log_failure(message: Any, error: Any, fallback: Any=("sync", "failed")) -> Any:
    stage, reason = failure_diagnostic(error) or fallback
    log.error("%s; stage=%s reason=%s", message, stage, reason)


@contextmanager
def private_broker_logs() -> Iterator[None]:
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
