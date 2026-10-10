"""Exercise real connector actions through synthetic HTTP, without broker access."""

from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import degiro_to_ghostfolio as adapter


USERNAME = "USERNAME_SENTINEL_934"
PASSWORD = "PASSWORD_SENTINEL_934"
SESSION = "SESSION_SENTINEL_934"
OTP = "123456"
SEED = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def credentials(monkeypatch):
    for key, value in zip(("DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET"),
                          (USERNAME, PASSWORD, SEED)):
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DEGIRO_ACCOUNT", json.dumps({"username": "wrong", "password": "wrong"}))
    import pyotp
    monkeypatch.setattr(pyotp.TOTP, "now", lambda self: OTP)


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


def broker_http(monkeypatch, fail_path=None, failure=None, cash_without_id=False):
    calls = []

    def send(self, request, **kwargs):
        parts = urlsplit(request.url)
        path = parts.path
        calls.append((request, kwargs))
        logging.getLogger("urllib3.connectionpool").debug("%s %s", request.url, PASSWORD)
        if fail_path and fail_path in path:
            if isinstance(failure, Exception):
                raise failure
            return failure
        if path.endswith("/login/totp"):
            body = json.loads(request.body)
            assert body["username"] == USERNAME
            assert body["password"] == PASSWORD
            assert body["oneTimePassword"] == OTP
            return response({"sessionId": SESSION, "status": 0})
        if path.endswith("/client"):
            return response({"data": {"intAccount": 123, "username": USERNAME}})
        if path.endswith("/transactions"):
            query = parse_qs(parts.query)
            assert query["groupTransactionsByOrder"] == ["False"]
            assert query["intAccount"] == ["123"]
            return response({"data": [{"id": 10, "productId": 20, "quantity": 0.5,
                "price": 10, "total": -5, "totalInBaseCurrency": -5,
                "fxRate": 1, "grossFxRate": 1, "feeInBaseCurrency": 0,
                "autoFxFeeInBaseCurrency": 0, "totalFeesInBaseCurrency": 0}]})
        if path.endswith("/order-history"):
            return response({"data": [{"orderId": "synthetic-order", "productId": 20,
                                        "status": "CONFIRMED"}]})
        if path.endswith("/accountoverview"):
            cash = {"id": 11, "productId": 20, "orderId": "opaque",
                    "unsettledCash": 0, "description": "unknown pending characterization"}
            if cash_without_id:
                cash.pop("id")
            return response({"data": {"cashMovements": [cash]}})
        if path.endswith("/products/info"):
            assert json.loads(request.body) == [20]
            return response({"data": {"20": {"isin": "TESTISIN", "symbol": "TEST"}}})
        if "/account/info/" in path:
            return response({"data": {"currency": "EUR"}})
        if "/update/" in path:
            query = parse_qs(parts.query)
            assert all(query[key] == ["0"] for key in ("portfolio", "cashFunds", "totalPortfolio"))
            return response({"portfolio": {}, "cashFunds": {}, "totalPortfolio": {}})
        if path.endswith("cashAccountReport/csv"):
            result = response({})
            result.encoding = "ISO-8859-1"
            result._content = "Date,Description,Change\n2026-01-01,Impôts sur dividende,1\n".encode("utf-8")
            return result
        if "/logout;" in path:
            return response({})
        pytest.fail("Unexpected broker endpoint")

    monkeypatch.setattr(requests.Session, "send", send)
    return calls


def assert_no_secrets(text):
    for secret in (USERNAME, PASSWORD, SESSION, OTP, SEED):
        assert secret not in text


def test_env_only_credentials(credentials):
    model = adapter.broker_credentials()
    assert model.username == USERNAME and model.password == PASSWORD
    assert model.totp_secret_key == SEED and model.int_account is None


@pytest.mark.parametrize("name", ["DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_credentials_fail_before_network(credentials, monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="Missing DEGIRO"):
        adapter.broker_credentials()


def test_real_actions_preserve_raw_fields_and_fractional_quantity(credentials, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls = broker_http(monkeypatch)
    data = adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 5), window_days=3)
    assert len(data["transactions"]) == len(data["cash_movements"]) == 1
    assert data["transactions"][0]["quantity"] == 0.5
    assert data["cash_movements"][0]["orderId"] == "opaque"
    assert data["history_completeness_verified"] is False
    assert "session_id" not in data and "credentials" not in data
    assert len([r for r, _ in calls if "/login/" in r.url]) == 1
    assert "/logout;" in calls[-1][0].url
    for _, settings in calls:
        assert settings["timeout"] == (10, 30)
        assert settings["allow_redirects"] is False
        assert settings["verify"] is True
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("path", ["/client", "/transactions", "/accountoverview",
                                  "/products/info", "/account/info/", "/update/", "/logout;"])
@pytest.mark.parametrize("failure", [
    response({"error": PASSWORD, "sessionId": SESSION}, 500),
    response(None), response({"unexpected": PASSWORD}),
    requests.Timeout(PASSWORD + SESSION), ValueError(PASSWORD + SESSION),
])
def test_read_failures_are_secret_free_and_logout_is_attempted(
        credentials, monkeypatch, caplog, path, failure):
    caplog.set_level(logging.DEBUG)
    calls = broker_http(monkeypatch, path, failure)
    if path == "/logout;" and isinstance(failure, requests.Response) and failure.status_code == 200:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
        assert_no_secrets(caplog.text)
        return
    with pytest.raises(RuntimeError) as caught:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
    assert "/logout;" in calls[-1][0].url
    assert caught.value.__suppress_context__
    assert_no_secrets(str(caught.value) + caplog.text)


@pytest.mark.parametrize("failure", [
    response({"error": PASSWORD}, 405),
    response({}, 302), response({"status": 6, "error": PASSWORD}, 400),
    response({"status": 12, "inAppToken": PASSWORD}, 400),
    response({"status": 1, "captchaRequired": True, "error": PASSWORD}, 400),
    response({"bad": PASSWORD}), requests.Timeout(PASSWORD), ValueError(SESSION),
])
def test_login_no_retry_no_maintenance_scrape_no_secret_logs(credentials, monkeypatch, caplog, failure):
    caplog.set_level(logging.DEBUG)
    calls = broker_http(monkeypatch, "/login/totp", failure)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("Maintenance scrape forbidden"))
    with pytest.raises(RuntimeError) as caught:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
    assert len(calls) == 1
    assert_no_secrets(str(caught.value) + caplog.text)


@pytest.mark.parametrize("method,url", [
    ("GET", "https://evil.example/pa/secure/client"),
    ("GET", "http://trader.degiro.nl/pa/secure/client"),
    ("POST", "https://trader.degiro.nl/trading/secure/v5/order"),
    ("DELETE", "https://trader.degiro.nl/trading/secure/v5/order"),
    ("GET", "https://trader.degiro.nl:443/pa/secure/client"),
])
def test_transport_refuses_other_hosts_and_trading_endpoints(monkeypatch, method, url):
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: pytest.fail("Forbidden request sent"))
    session = adapter.bounded_broker_session()
    with pytest.raises(RuntimeError, match="outside read-only"):
        session.send(session.prepare_request(requests.Request(method, url)))
    session.close()


def test_bounded_session_preserves_canonical_connector_headers():
    from degiro_connector.core.constants.headers import HEADERS
    session = adapter.bounded_broker_session()
    assert all(session.headers[key] == value for key, value in HEADERS.items())
    assert session.trust_env is False
    assert session.get_adapter("https://").max_retries.total == 0
    session.close()


def test_history_overlaps_one_day_and_is_bounded():
    assert adapter.history_windows(date(2026, 1, 1), date(2026, 1, 5), 3) == [
        (date(2026, 1, 1), date(2026, 1, 3)), (date(2026, 1, 3), date(2026, 1, 5))]
    with pytest.raises(RuntimeError, match="budget"):
        adapter.history_windows(date(2020, 1, 1), date(2026, 1, 1), 2)


def test_overlap_conflicts_fail_and_unknown_ids_are_not_synthesized():
    rows = [{"id": 1, "price": 10}]
    assert adapter.merge_history(rows, [{"id": 1, "price": 10}]) == rows
    with pytest.raises(RuntimeError, match="Conflicting"):
        adapter.merge_history(rows, [{"id": 1, "price": 11}])
    with pytest.raises(RuntimeError, match="stable identity"):
        adapter.merge_history(rows, [{"price": 11}])


def test_connector_none_is_failure():
    def no_data():
        return None
    with pytest.raises(RuntimeError, match="returned no data"):
        adapter.broker_call(no_data)


def test_overlapping_cash_without_identity_fails_with_logout(credentials, monkeypatch):
    calls = broker_http(monkeypatch, cash_without_id=True)
    with pytest.raises(RuntimeError):
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 5), 3)
    assert "/logout;" in calls[-1][0].url


def test_private_snapshot_redacts_auth_and_refuses_overwrite(tmp_path):
    path = tmp_path / "financial.json"
    adapter.save_private_snapshot({"sessionId": SESSION, "data": {"token": PASSWORD, "amount": 1}}, path)
    assert json.loads(path.read_text()) == {"data": {"amount": 1}}
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        adapter.save_private_snapshot({}, path)
    with pytest.raises(RuntimeError, match="outside Git"):
        adapter.save_private_snapshot({}, Path(adapter.__file__).parent / "private.json")


def test_logging_settings_restored():
    logger = logging.getLogger("urllib3.connectionpool")
    before = (logger.level, logger.disabled, logger.propagate)
    with adapter.private_broker_logs():
        assert logger.disabled
    assert (logger.level, logger.disabled, logger.propagate) == before


def test_optional_statement_is_bounded_and_private(credentials, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls = broker_http(monkeypatch)
    data = adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2), report_locale=("nl", "en"))
    assert data["account_report_csv"].startswith("Date,Description")
    assert "Impôts" in data["account_report_csv"]
    assert any("cashAccountReport/csv" in r.url for r, _ in calls)
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("failure", [response({}, 500), requests.Timeout(PASSWORD), response(None)])
def test_statement_failure_logs_out(credentials, monkeypatch, caplog, failure):
    caplog.set_level(logging.DEBUG)
    calls = broker_http(monkeypatch, "cashAccountReport/csv", failure)
    if isinstance(failure, requests.Response) and failure.status_code == 200:
        failure._content = b"<html>invalid report</html>"
    with pytest.raises(RuntimeError, match="account_report") as caught:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2), report_locale=("nl", "en"))
    assert "/logout;" in calls[-1][0].url
    assert_no_secrets(str(caught.value) + caplog.text)


@pytest.mark.parametrize("identity", [True, 1.2, "12.0", 0, -1, "garbage"])
def test_product_identity_is_never_truncated(identity):
    with pytest.raises(RuntimeError, match="product identity"):
        adapter.history_product_ids([{"productId": identity}])


def test_cli_checks_private_destination_before_authentication(monkeypatch, tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("{}")
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Must validate locally first"))
    assert adapter.main(["--read-only", "--from-date", "2026-01-01", "--to-date", "2026-01-02",
                         "--output", str(path)]) == 1


def test_cli_never_logs_uncontrolled_exception(monkeypatch, caplog, tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError(PASSWORD + SESSION)
    monkeypatch.setattr(adapter, "read_degiro", fail)
    assert adapter.main(["--read-only", "--from-date", "2026-01-01", "--to-date", "2026-01-02",
                         "--output", str(tmp_path / "unused.json")]) == 1
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("body,status,expected", [
    ({"error": PASSWORD}, 401, "http_401"),
    ({"error": PASSWORD}, 403, "http_403"),
    ({"error": PASSWORD}, 405, "maintenance"),
    ({"error": PASSWORD}, 302, "redirect_refused"),
    ({"status": 6, "error": PASSWORD}, 400, "totp_required"),
    ({"status": 12, "error": PASSWORD}, 400, "in_app_required"),
    ({"status": 1, "captchaRequired": True, "error": PASSWORD}, 400, "captcha_required"),
])
def test_login_diagnostics_are_fixed_codes(credentials, monkeypatch, body, status, expected):
    broker_http(monkeypatch, "/login/totp", response(body, status))
    with pytest.raises(RuntimeError, match=f"DEGIRO login failed: {expected}") as caught:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
    assert_no_secrets(str(caught.value))


def test_cash_overlap_ignores_only_window_dependent_balance():
    rows = [{"id": 1, "change": 2, "currency": "EUR", "balance": {"EUR": 100}}]
    adapter.merge_history(rows, [{**rows[0], "balance": {"EUR": 200}}], cash=True)
    assert len(rows) == 1
    with pytest.raises(RuntimeError, match="Conflicting"):
        adapter.merge_history(rows, [{**rows[0], "change": 3}], cash=True)
    with pytest.raises(RuntimeError, match="Conflicting"):
        adapter.merge_history(rows, [{**rows[0], "balance": {"EUR": 200}}])


def test_optional_order_history_and_snapshot_freshness(credentials, monkeypatch):
    broker_http(monkeypatch)
    result = adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 5), 3, orders=True)
    assert len(result["orders"]) == 1
    assert result["fetch_started_at"] <= result["fetched_at"]
    assert result["fetched_at"].endswith("+00:00")


def test_order_history_failure_logs_out(credentials, monkeypatch):
    calls = broker_http(monkeypatch, "/order-history", response({}, 500))
    with pytest.raises(RuntimeError, match="order_history"):
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2), orders=True)
    assert "/logout;" in calls[-1][0].url


def test_prospective_reader_fetches_held_metadata_and_captures_destination_inside_interval(
        credentials, monkeypatch, caplog):
    calls = broker_http(monkeypatch)
    original = requests.Session.send
    extra_products = []
    def send(session, request, **kwargs):
        path = urlsplit(request.url).path
        if "/update/" in path:
            return response({"portfolio": {"value": [{"id": "21", "name": "positionrow",
                "value": [{"name": "id", "value": "21"}, {"name": "size", "value": 10}]}]},
                "cashFunds": {"value": []}, "totalPortfolio": {"value": []}})
        if path.endswith("/products/info") and json.loads(request.body) == [21]:
            extra_products.append(21)
            return response({"data": {"21": {"id": "21", "isin": "TESTHELD"}}})
        return original(session, request, **kwargs)
    monkeypatch.setattr(requests.Session, "send", send)
    observed = []
    def destination():
        observed.append("read-only target")
        return {"captured_at": datetime.now(timezone.utc).isoformat(), "account": {"id": "synthetic"}}
    data = adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2), holdings=True,
        cutover_target_reader=destination)
    assert extra_products == [21] and data['products']['21']['isin'] == 'TESTHELD'
    assert observed == ['read-only target']
    assert data['fetch_started_at'] <= data['opening_destination']['captured_at'] <= data['fetched_at']
    assert '/logout;' in calls[-1][0].url
    assert_no_secrets(caplog.text)


def test_cutover_destination_failure_is_private_and_still_logs_out(credentials, monkeypatch, caplog):
    calls = broker_http(monkeypatch)
    def destination():
        raise RuntimeError(PASSWORD + SESSION)
    with pytest.raises(RuntimeError, match='cutover_destination') as error:
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2), cutover_target_reader=destination)
    assert '/logout;' in calls[-1][0].url
    assert_no_secrets(str(error.value) + caplog.text)
