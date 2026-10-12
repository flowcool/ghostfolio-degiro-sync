"""CLI diagnostics must distinguish failures without rendering runtime values."""
import os
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import requests

import degiro_to_ghostfolio as adapter
from test_degiro_read import credentials, broker_http, USERNAME, PASSWORD, SESSION, OTP, SEED
from test_vault_credentials import vault, mock_cli, SECRETS


SECRET = "PRIVATE_PASSWORD_TOKEN_https://private.example/financial-record"


def assert_private(caplog, capsys):
    captured = capsys.readouterr()
    rendered = caplog.text + captured.out + captured.err
    for value in (SECRET, USERNAME, PASSWORD, SESSION, OTP, SEED, *SECRETS.values(),
                  "BROKER-USER-SENTINEL", "BROKER-PASSWORD-SENTINEL", "c2Vzc2lvbg=="):
        assert value not in rendered


def read_arguments(tmp_path, *extra):
    return ["--read-only", "--from-date", "2026-01-01", "--to-date", "2026-01-02",
            "--output", str(tmp_path / "capture.json"), *extra]


def test_invalid_date_has_safe_diagnostic_before_broker(monkeypatch, tmp_path, caplog, capsys):
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(["--read-only", "--from-date", SECRET, "--to-date", "2026-01-02",
                         "--output", str(tmp_path / "capture.json")]) == 1
    assert "stage=config reason=date_range" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("arguments", [["--private-key", SECRET], ["--window-days", SECRET],
                                       ["--sync", "--read-only"], ["--sync", "--output"]])
def test_argparse_errors_never_echo_values(arguments, caplog, capsys):
    assert adapter.main(arguments) == 2
    assert "stage=config reason=arguments" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("window", ["1", "367", "-90"])
def test_window_range_is_distinct_from_date_errors(monkeypatch, tmp_path, caplog, capsys, window):
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(read_arguments(tmp_path, "--window-days", window)) == 1
    assert "stage=config reason=window_days" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("change,reason", [("mapping-schema", "mapping"), ("mapping-read", "mapping"),
    ("mapping-yaml", "mapping"), ("state", "state_dir"), ("account", "account"),
    ("mode", "sync_mode"), ("credential", "ghostfolio_credentials"), ("lookback", "lookback_days")])
def test_sync_configuration_fails_before_auth(monkeypatch, tmp_path, caplog, capsys, change, reason):
    values = {"SYNC_MODE": "rolling", "DRY_RUN": "1", "LOOKBACK_DAYS": "90",
              "GHOST_HOST": "https://portfolio.example", "GHOST_TOKEN": SECRET,
              "GHOST_ACCOUNT_ID": "synthetic", "DEGIRO_ACCOUNT_ID": "123",
              "MAPPING_FILE": str(tmp_path / "mapping.yaml"), "STATE_DIR": str(tmp_path / "state")}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GHOST_ACCESS_TOKEN", raising=False)
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("US0378331005: {symbol: AAPL, currency: USD}")
    if change == "mapping-schema":
        mapping.write_text("US0378331005: {symbol: AAPL, currency: CHF}")
    elif change == "mapping-read":
        monkeypatch.setenv("MAPPING_FILE", str(tmp_path / SECRET.split('/')[0]))
    elif change == "mapping-yaml":
        mapping.write_text("[" + SECRET)
    elif change == "account":
        monkeypatch.setenv("DEGIRO_ACCOUNT_ID", SECRET)
    elif change == "mode":
        monkeypatch.setenv("SYNC_MODE", SECRET)
    elif change == "credential":
        monkeypatch.setenv("GHOST_ACCESS_TOKEN", SECRET)
    elif change == "lookback":
        monkeypatch.setenv("LOOKBACK_DAYS", SECRET)
    monkeypatch.setattr(adapter, "authenticate_ghostfolio", lambda *a: pytest.fail("Ghostfolio contacted"))
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(["--sync"]) == 1
    assert f"stage=config reason={reason}" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("command,reason", [("config", "server"), ("login", "login"),
    ("unlock", "unlock"), ("sync", "sync"), ("get", "item"), ("logout", "logout")])
def test_vault_command_failure_reaches_cli_without_secrets(vault, monkeypatch, tmp_path, caplog, capsys, command, reason):
    calls, directories = mock_cli(monkeypatch, vault, command)
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert f"stage=vault reason={reason}" in caplog.text
    assert not any(path.exists() for path in directories)
    assert_private(caplog, capsys)


def test_missing_vault_configuration_is_distinct(vault, monkeypatch, tmp_path, caplog, capsys):
    monkeypatch.delenv("BW_PASSWORD")
    monkeypatch.setattr(adapter.subprocess, "run", lambda *a, **k: pytest.fail("CLI contacted"))
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=vault reason=configuration" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("stage,path,extra", [
    ("login", "/login/", []), ("client_discovery", "/client", []),
    ("transactions", "/transactions", []), ("account_overview", "/accountoverview", []),
    ("products", "/products/info", []), ("account_info", "/account/info/", []),
    ("account_update", "/update/", []), ("account_report", "cashAccountReport/csv", ["--report-country", "fr", "--report-language", "fr"]),
    ("order_history", "/order-history", ["--orders"]), ("logout", "/logout;", [])])
def test_real_connector_stages_reach_cli(credentials, monkeypatch, tmp_path, caplog, capsys, stage, path, extra):
    broker_http(monkeypatch, fail_path=path, failure=requests.RequestException(SECRET))
    assert adapter.main(read_arguments(tmp_path, *extra)) == 1
    assert f"stage={stage} reason=" in caplog.text
    assert_private(caplog, capsys)


def test_broker_stage_survives_sync_catch_all(credentials, monkeypatch, caplog, capsys):
    broker_http(monkeypatch, fail_path="/transactions", failure=requests.RequestException(SECRET))
    config = {"dry_run": True, "sync_mode": "full_history", "target_account": "synthetic",
              "ghost_host": "https://portfolio.example", "ghost_token": SECRET}
    monkeypatch.setattr(adapter, "load_sync_config", lambda: (config, {}, {}))
    monkeypatch.setenv("LOOKBACK_DAYS", "90")
    monkeypatch.setenv("SYNC_MODE", "full_history")
    assert adapter.main(["--sync", "--from-date", "2026-01-01", "--to-date", "2026-01-02"]) == 1
    assert "stage=transactions reason=failed" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("metadata", [(SECRET, "failed"), ("login", SECRET), ["login", "failed"],
                                      ("login", "failed", SECRET), ({"private": SECRET}, "failed"), None])
def test_forged_diagnostics_and_exception_text_are_not_rendered(monkeypatch, tmp_path, caplog, capsys, metadata):
    def refused(*args, **kwargs):
        error = RuntimeError(SECRET)
        error.sync_diagnostic = metadata
        raise error
    monkeypatch.setattr(adapter, "read_degiro", refused)
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=broker reason=read" in caplog.text
    assert_private(caplog, capsys)


def test_output_collision_is_identified_and_preserves_file(monkeypatch, tmp_path, caplog, capsys):
    destination = tmp_path / "capture.json"
    destination.write_text(SECRET)
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=output reason=destination" in caplog.text
    assert destination.read_text() == SECRET
    assert_private(caplog, capsys)


def test_ghostfolio_exchange_failure_is_identified(monkeypatch, tmp_path, caplog, capsys):
    monkeypatch.setenv("GHOST_HOST", "https://portfolio.example")
    monkeypatch.setenv("GHOST_ACCESS_TOKEN", SECRET)
    monkeypatch.delenv("GHOST_TOKEN", raising=False)
    def refused(*args, **kwargs):
        raise requests.RequestException(SECRET)
    monkeypatch.setattr(adapter, "ghost_exchange_access_token", refused)
    assert adapter.main(["--ghost-accounts", "--output", str(tmp_path / "accounts.json")]) == 1
    assert "stage=ghostfolio reason=authentication" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("reason", ["account_read", "activities_read"])
def test_ghostfolio_reads_have_distinct_private_diagnostics(monkeypatch, caplog, capsys, reason):
    config = {"dry_run": True, "sync_mode": "full_history", "target_account": "synthetic",
              "ghost_host": "https://portfolio.example", "ghost_token": SECRET}
    monkeypatch.setattr(adapter, "load_sync_config", lambda: (config, {}, {}))
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: {"account_info": {"baseCurrency": "EUR"}})
    monkeypatch.setenv("LOOKBACK_DAYS", "90")
    monkeypatch.setenv("SYNC_MODE", "full_history")
    calls = []
    def get(url):
        calls.append(url)
        if len(calls) == (1 if reason == "account_read" else 2):
            raise requests.RequestException(SECRET)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {})
    @contextmanager
    def transport(*args):
        yield SimpleNamespace(get=get)
    monkeypatch.setattr(adapter, "ghost_transport", transport)
    assert adapter.main(["--sync", "--from-date", "2026-01-01", "--to-date", "2026-01-02"]) == 1
    assert f"stage=ghostfolio reason={reason}" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("value", ["", SECRET])
def test_direct_credentials_are_identified_even_when_empty(credentials, monkeypatch, tmp_path, caplog, capsys, value):
    monkeypatch.setenv("DEGIRO_PASSWORD", value)
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: pytest.fail("Broker contacted"))
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=config reason=direct_credentials" in caplog.text
    assert_private(caplog, capsys)


def test_invalid_report_locale_is_private(monkeypatch, tmp_path, caplog, capsys):
    monkeypatch.setattr(adapter, "broker_credentials", lambda: pytest.fail("Vault contacted"))
    assert adapter.main(read_arguments(tmp_path, "--report-country", SECRET, "--report-language", "fr")) == 1
    assert "stage=config reason=report_locale" in caplog.text
    assert_private(caplog, capsys)


def test_cutover_read_failure_retains_its_stage(credentials, monkeypatch, tmp_path, caplog, capsys):
    broker_http(monkeypatch)
    read = adapter.read_degiro
    def refused():
        raise RuntimeError(SECRET)
    def with_cutover(*args, **kwargs):
        return read(*args, **kwargs, cutover_target_reader=refused)
    monkeypatch.setattr(adapter, "read_degiro", with_cutover)
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=cutover_destination reason=failed" in caplog.text
    assert_private(caplog, capsys)


def test_output_write_failure_does_not_render_path(monkeypatch, tmp_path, caplog, capsys):
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: {})
    def refused(*args, **kwargs):
        raise OSError(SECRET)
    monkeypatch.setattr(adapter, "save_private_snapshot", refused)
    assert adapter.main(read_arguments(tmp_path)) == 1
    assert "stage=output reason=write" in caplog.text
    assert_private(caplog, capsys)


@pytest.mark.parametrize("arguments,code,token", [
    (["--window-days", SECRET], 2, "stage=config reason=arguments"),
    (["--sync"], 1, "stage=config reason=ghostfolio_credentials"),
    ([], 1, "stage=config reason=mode")])
def test_process_stdout_stderr_are_private(arguments, code, token):
    # A minimal synthetic environment guarantees failure before network/CLI use.
    environment = {"PATH": os.environ["PATH"], "GHOST_HOST": "https://portfolio.example",
                   "GHOST_TOKEN": SECRET, "GHOST_ACCESS_TOKEN": SECRET, "LOOKBACK_DAYS": "90",
                   "SYNC_MODE": "full_history"}
    result = subprocess.run([sys.executable, adapter.__file__, *arguments], env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == code
    assert token in result.stderr
    assert result.stdout == ""
    assert SECRET not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
