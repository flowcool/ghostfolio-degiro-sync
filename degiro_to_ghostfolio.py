#!/usr/bin/env python3
"""Read-only DEGIRO adapter; activity writes require the remaining validation gates."""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests

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
        raise RuntimeError("Invalid DEGIRO data envelope")
    rows = envelope["data"]
    if collection:
        if not isinstance(rows, dict) or collection not in rows:
            raise RuntimeError("Invalid DEGIRO cash envelope")
        rows = rows[collection]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Invalid DEGIRO history rows")
    return rows


def merge_history(existing, rows, require_ids=True, cash=False, identity_field="id"):
    """Keep equal overlap rows once; reject missing identities or conflicting content."""
    for row in rows:
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


def read_degiro(from_date, to_date, window_days=90, report_locale=None, orders=False):
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
        except Exception:
            reason = getattr(session, "degiro_diagnostics", {}).get("auth_reason")
            if stage == "login" and reason in AUTH_FAILURE_REASONS:
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
    """Only an explicit read-only command can contact DEGIRO at this phase."""
    if not argv:
        log.error("DEGIRO sync gates incomplete; use explicit --read-only characterization")
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-country")
    parser.add_argument("--report-language")
    parser.add_argument("--orders", action="store_true")
    args = parser.parse_args(argv)
    try:
        output = snapshot_destination(args.output)
        locale = None
        if args.report_country or args.report_language:
            locale = (args.report_country, args.report_language)
        data = read_degiro(date.fromisoformat(args.from_date), date.fromisoformat(args.to_date),
                           args.window_days, report_locale=locale, orders=args.orders)
        save_private_snapshot(data, output)
    except Exception as error:
        stages = ("login", "client_discovery", "transactions", "account_overview", "products",
                  "account_info", "account_update", "account_report", "order_history")
        messages = {f"DEGIRO read failed at {stage}; no financial writes attempted" for stage in stages}
        messages.add("DEGIRO logout failed")
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
