"""Bounded broker reads; no financial broker mutations."""

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import requests

from ghostfolio_degiro_sync import vault
from ghostfolio_degiro_sync.accounting import (
    API_FORMAT_ERRORS,
    CASH_CURRENCIES,
    cash_wrapper_rows,
    check_api_import_format,
    financial_decimal,
    merge_history,
    named_values,
)
from ghostfolio_degiro_sync.diagnostics import (
    AUTH_FAILURE_REASONS,
    diagnostic_boundary,
    private_broker_logs,
    tag_failure,
)
from ghostfolio_degiro_sync.identity import broker_identity

BROKER_TIMEOUT = (10, 30)
MAX_HISTORY_WINDOWS = 120
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


def quiet_broker_logger() -> logging.Logger:
    logger = logging.Logger("degiro_adapter.silent")
    logger.disabled = True
    logger.propagate = False
    return logger


def bounded_broker_session() -> Any:
    """No retries, redirects or order endpoints; reject maintenance before scraping."""
    from degiro_connector.core.constants.headers import HEADERS
    session: Any = requests.Session()
    session.headers.update(HEADERS)
    session.trust_env = False
    diagnostics: dict[str, str] = {}
    session.degiro_diagnostics = diagnostics
    session.degiro_evidence = []
    original_send = session.send

    def send(request: Any, **kwargs: Any) -> Any:
        parts = urlsplit(request.url)
        paths = BROKER_PATHS.get(request.method, ())
        if (parts.scheme != "https" or parts.netloc != "trader.degiro.nl"
                or parts.fragment or not any(re.fullmatch(path, parts.path) for path in paths)):
            raise RuntimeError("DEGIRO request outside read-only boundary")
        kwargs.update(timeout=BROKER_TIMEOUT, allow_redirects=False, verify=True, stream=False)
        try:
            response = original_send(request, **kwargs)
        except Exception as error:
            diagnostics["auth_reason"] = (
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
            diagnostics["auth_reason"] = reason
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
        if parts.path in ("/portfolio-reports/secure/v4/transactions",
                "/portfolio-reports/secure/v6/accountoverview", "/product_search/secure/v5/products/info"):
            content = getattr(response, "content", None)
            if isinstance(content, bytes) and content:
                try:
                    wire = content.decode("utf-8")
                except UnicodeError:
                    wire = ""
                if wire:
                    session.degiro_evidence.append({"path": parts.path, "body": wire})
        return response

    session.send = send
    return session


def broker_call(action: Any, **kwargs: Any) -> Any:
    try:
        result = action(**kwargs)
    except Exception:
        raise RuntimeError(f"DEGIRO {action.__name__} failed") from None
    if result is None:
        raise RuntimeError(f"DEGIRO {action.__name__} returned no data")
    return result


def history_windows(from_date: date, to_date: date, window_days: int=90) -> list[tuple[date, date]]:
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


def raw_rows(envelope: Any, collection: str | None=None) -> list[dict[str, Any]]:
    if not isinstance(envelope, dict) or "data" not in envelope:
        raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    rows = envelope["data"]
    if collection:
        # Observed accountoverview response for an empty recent interval.
        # Prospective acceptance still requires independently corroborated statements.
        if collection == "cashMovements" and rows == {}:
            return []
        if not isinstance(rows, dict) or collection not in rows:
            raise RuntimeError(API_FORMAT_ERRORS["unknown"])
        rows = rows[collection]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError(API_FORMAT_ERRORS["unknown"])
    return rows





def history_product_ids(rows: list[dict[str, Any]]) -> list[int]:
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


def read_degiro(from_date: date, to_date: date, window_days: int=90, report_locale: tuple[str, str] | None=None, orders: bool=False, holdings: bool=False,
                cutover_target_reader: Callable[[], object] | None=None) -> dict[str, Any]:
    """Fetch raw private data with one login and guaranteed bounded logout attempt."""
    from degiro_connector.trading.actions.action_connect import ActionConnect
    from degiro_connector.trading.actions.action_get_account_info import (
        ActionGetAccountInfo,
    )
    from degiro_connector.trading.actions.action_get_account_overview import (
        ActionGetAccountOverview,
    )
    from degiro_connector.trading.actions.action_get_account_report import (
        ActionGetAccountReport,
    )
    from degiro_connector.trading.actions.action_get_client_details import (
        ActionGetClientDetails,
    )
    from degiro_connector.trading.actions.action_get_orders_history import (
        ActionGetOrdersHistory,
    )
    from degiro_connector.trading.actions.action_get_products_info import (
        ActionGetProductsInfo,
    )
    from degiro_connector.trading.actions.action_get_transactions_history import (
        ActionGetTransactionsHistory,
    )
    from degiro_connector.trading.actions.action_get_update import ActionGetUpdate
    from degiro_connector.trading.actions.action_logout import ActionLogout
    from degiro_connector.trading.models.account import (
        OverviewRequest,
        ReportRequest,
        UpdateOption,
        UpdateRequest,
    )
    from degiro_connector.trading.models.order import (
        HistoryRequest as OrderHistoryRequest,
    )
    from degiro_connector.trading.models.transaction import HistoryRequest

    with diagnostic_boundary("config", "date_range"):
        windows = history_windows(from_date, to_date, window_days)
    if report_locale is not None and (
            not isinstance(report_locale, tuple) or len(report_locale) != 2
            or any(not isinstance(part, str) or not re.fullmatch(r"[a-z]{2}", part)
                   for part in report_locale)):
        raise tag_failure(RuntimeError("Invalid DEGIRO report locale"), "config", "report_locale")
    credentials = vault.broker_credentials()
    logger = quiet_broker_logger()
    session = bounded_broker_session()
    session_id = None
    failure = None
    data: dict[str, Any] = {"transactions": [], "cash_movements": [], "products": {}, "orders": [],
            "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
            "fetch_started_at": datetime.now(UTC).isoformat(),
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
                    held_identity = row.get("id")
                    fields = named_values(row["value"])
                    if held_identity in identities or fields.get("id") != held_identity:
                        raise RuntimeError("Conflicting prospective holding identity")
                    identities.add(held_identity)
                    if isinstance(held_identity, str) and held_identity.startswith("FLATEX_"):
                        continue
                    if (held_identity in CASH_CURRENCIES
                            and fields.get("positionType") == "CASH"
                            and financial_decimal(fields.get("size")) == 0):
                        continue
                    product_id = broker_identity(held_identity)
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
            wire = getattr(session, "degiro_evidence", None)
            if wire:
                data["_diagnostic_wire"] = list(wire)
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
            tag_failure(failure, stage, reason if stage == "login" and reason in AUTH_FAILURE_REASONS else "failed")
        finally:
            if session_id:
                try:
                    ok = broker_call(ActionLogout.logout, credentials=credentials,
                                     session_id=session_id, session=session, logger=logger)
                    if ok is not True:
                        raise RuntimeError("DEGIRO logout failed")
                except Exception:
                    failure = failure or tag_failure(RuntimeError("DEGIRO logout failed"), "logout", "failed")
            session.close()
    if failure:
        raise failure from None
    data["fetched_at"] = datetime.now(UTC).isoformat()
    with diagnostic_boundary("broker", "api_format"):
        check_api_import_format(data)
    return data
