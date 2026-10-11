"""Fresh vault retrieval and failures use synthetic subprocesses only."""
import json
import os
from pathlib import Path
import subprocess
import traceback

import pytest

import degiro_to_ghostfolio as adapter

ITEM = "12345678-1234-4234-8234-123456789abc"
SEED = "JBSWY3DPEHPK3PXP"
SECRETS = {"BW_ITEM_ID": ITEM, "BW_CLIENTID": "user.CLIENT-SENTINEL",
           "BW_CLIENTSECRET": "API-SECRET-SENTINEL", "BW_PASSWORD": "MASTER-SENTINEL"}


@pytest.fixture
def vault(monkeypatch):
    for name in ("DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET", "BW_SESSION"):
        monkeypatch.delenv(name, raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("BW_SERVER", "https://vault.example")
    # Credentials unrelated to the CLI must not reach its process environment.
    monkeypatch.setenv("GHOST_TOKEN", "GHOST-SENTINEL")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid")
    return {"id": ITEM, "type": 1, "login": {"username": "BROKER-USER-SENTINEL",
            "password": "BROKER-PASSWORD-SENTINEL", "totp": SEED}}


def mock_cli(monkeypatch, item, fail=None):
    calls, directories = [], []
    def run(command, **options):
        calls.append(command[1:])
        environment = options["env"]
        directory = Path(environment["BITWARDENCLI_APPDATA_DIR"])
        directories.append(directory)
        assert directory.is_dir() and directory.stat().st_mode & 0o777 == 0o700
        assert not set(environment) & {"GHOST_TOKEN", "DEGIRO_PASSWORD", "HTTP_PROXY"}
        assert options["stdin"] == subprocess.DEVNULL and options["stderr"] == subprocess.DEVNULL
        assert 0 < options["timeout"] <= 30
        assert not any(value in " ".join(command) for key, value in SECRETS.items() if key != "BW_ITEM_ID")
        if command[1] == fail:
            raise subprocess.TimeoutExpired(command, 30, output=b"MASTER-SENTINEL")
        body = json.dumps(item) if command[1] == "get" else (
            "c2Vzc2lvbg==" if command[1] == "unlock" else "")
        if command[1] in ("sync", "get", "logout"):
            assert environment["BW_SESSION"] == "c2Vzc2lvbg=="
        return subprocess.CompletedProcess(command, 0, body.encode())
    monkeypatch.setattr(subprocess, "run", run)
    return calls, directories


def test_fresh_item_each_execution_and_temporary_state_removed(vault, monkeypatch, caplog):
    calls, directories = mock_cli(monkeypatch, vault)
    first = adapter.broker_credentials()
    vault["login"]["password"] = "ROTATED-PASSWORD-SENTINEL"
    second = adapter.broker_credentials()
    assert first.password == "BROKER-PASSWORD-SENTINEL" and second.password == "ROTATED-PASSWORD-SENTINEL"
    assert first.totp_secret_key == SEED
    assert [call[0] for call in calls] == ["config", "login", "unlock", "sync", "get", "logout"] * 2
    assert directories[0] != directories[-1] and not any(p.exists() for p in directories)
    assert all(value not in caplog.text for value in SECRETS.values())
    assert "BW_SESSION" not in os.environ


@pytest.mark.parametrize("stage", ["config", "login", "unlock", "sync", "get", "logout"])
def test_failure_is_private_and_never_constructs_broker_credentials(vault, monkeypatch, stage):
    calls, directories = mock_cli(monkeypatch, vault, stage)
    with pytest.raises(RuntimeError, match="Bitwarden credential retrieval failed") as error:
        adapter.broker_credentials()
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "MASTER-SENTINEL" not in rendered and "BROKER-PASSWORD-SENTINEL" not in rendered
    assert calls[-1][0] == (stage if stage in ("config", "login") else "logout")
    assert not any(p.exists() for p in directories)


@pytest.mark.parametrize("change", ["missing-key", "invalid-id", "both-sources", "http-server", "url-password"])
def test_invalid_configuration_refuses_cli_before_network(vault, monkeypatch, change):
    if change == "missing-key":
        monkeypatch.delenv("BW_PASSWORD")
    elif change == "invalid-id":
        monkeypatch.setenv("BW_ITEM_ID", "ambiguous-name")
    elif change == "both-sources":
        monkeypatch.setenv("DEGIRO_TOTP_SECRET", SEED)
    else:
        monkeypatch.setenv("BW_SERVER", "http://vault.example" if change == "http-server"
                           else "https://user:MASTER-SENTINEL@vault.example")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("CLI attempted"))
    with pytest.raises(RuntimeError):
        adapter.broker_credentials()


@pytest.mark.parametrize("change", ["wrong-id", "deleted", "type", "no-login", "no-seed", "temporary-otp", "hotp", "sha256", "digits", "interval"])
def test_item_and_totp_contract_reject_ambiguous_data(vault, monkeypatch, change):
    if change == "wrong-id":
        vault["id"] = "another-item"
    elif change == "deleted":
        vault["deletedDate"] = "2026-01-01"
    elif change == "type":
        vault["type"] = 2
    elif change == "no-login":
        vault["login"] = None
    else:
        vault["login"]["totp"] = {"no-seed": None, "temporary-otp": "123456",
            "hotp": f"otpauth://hotp/broker?secret={SEED}&counter=1",
            "sha256": f"otpauth://totp/broker?secret={SEED}&algorithm=SHA256",
            "digits": f"otpauth://totp/broker?secret={SEED}&digits=8",
            "interval": f"otpauth://totp/broker?secret={SEED}&period=60"}[change]
    mock_cli(monkeypatch, vault)
    with pytest.raises(RuntimeError, match="Bitwarden credential retrieval failed"):
        adapter.broker_credentials()


def test_otpauth_uri_supported(vault, monkeypatch):
    vault["login"]["totp"] = f"otpauth://totp/broker?secret={SEED}"
    mock_cli(monkeypatch, vault)
    assert adapter.broker_credentials().totp_secret_key == SEED


@pytest.mark.parametrize("failure", ["exit", "json", "oversize", "session", "deadline"])
def test_invalid_cli_results_fail_closed_and_remove_state(vault, monkeypatch, failure):
    calls, directories = mock_cli(monkeypatch, vault)
    original = subprocess.run
    def run(command, **options):
        result = original(command, **options)
        if command[1] == "get":
            if failure == "exit":
                result.returncode = 1
            if failure == "json":
                result.stdout = b"MASTER-SENTINEL-invalid-json"
            if failure == "oversize":
                result.stdout = b"x" * 2_000_001
        if command[1] == "unlock" and failure == "session":
            result.stdout = b"invalid session"
        return result
    monkeypatch.setattr(subprocess, "run", run)
    if failure == "deadline":
        ticks = iter([0, 121])
        monkeypatch.setattr(adapter.time, "monotonic", lambda: next(ticks, 121))
    with pytest.raises(RuntimeError, match="Bitwarden credential retrieval failed"):
        adapter.broker_credentials()
    assert not any(p.exists() for p in directories)


def test_vault_to_real_broker_actions_and_otp_timing(vault, monkeypatch, caplog):
    from datetime import date
    from test_degiro_read import broker_http, USERNAME, PASSWORD, OTP, assert_no_secrets
    import pyotp
    vault["login"].update(username=USERNAME, password=PASSWORD)
    calls, directories = mock_cli(monkeypatch, vault)
    def now(self):
        assert calls[-1][0] == "logout"
        assert not any(p.exists() for p in directories)
        assert self.secret == SEED
        return OTP
    monkeypatch.setattr(pyotp.TOTP, "now", now)
    broker_calls = broker_http(monkeypatch)
    snapshot = adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
    assert snapshot["source_account"] == "123"
    assert len([r for r, _ in broker_calls if "/login/" in r.url]) == 1
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("stage", ["config", "login", "unlock", "sync", "get", "logout"])
def test_vault_failure_prevents_any_broker_request(vault, monkeypatch, stage):
    from datetime import date
    import requests
    mock_cli(monkeypatch, vault, stage)
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: pytest.fail("Broker contacted"))
    with pytest.raises(RuntimeError, match="Bitwarden credential retrieval failed"):
        adapter.read_degiro(date(2026, 1, 1), date(2026, 1, 2))
