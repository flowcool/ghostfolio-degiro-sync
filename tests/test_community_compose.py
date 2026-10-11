"""Community configuration and proposal publication, entirely synthetic."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import degiro_to_ghostfolio as adapter


@pytest.mark.parametrize("host", ["https://portfolio.example", "https://vault.example:8443",
    "http://ghostfolio:3333", "http://localhost:3333", "http://127.0.0.1:3333",
    "http://192.168.10.2:3333", "http://[::1]:3333", "http://10.0.0.2"])
def test_portable_origins(host):
    assert adapter.validate_ghost_host(host) == host


@pytest.mark.parametrize("host", ["http://example.com", "http://8.8.8.8", "http://0.0.0.0",
    "http://[::]", "https://169.254.169.254", "https://[fe80::1]", "https://224.0.0.1",
    "https://portfolio.example/", "https://user:SECRET@portfolio.example",
    "https://portfolio.example?token=SECRET", "https://portfolio.example#SECRET",
    "https://portfolio.example:", "https://portfolio.example:0", "https://portfolio.example:65536",
    "https://portfolio.example:abc", "https://portfolio.example\\evil", "https://bad..example",
    "https://-bad.example", "https://bad-.example", "https://portfolio.example%2fSECRET",
    "https://Portfolio.example", "https://portfolio.example\n", " https://portfolio.example", None])
def test_invalid_origins_are_private(host):
    with pytest.raises(RuntimeError, match="origin policy") as error:
        adapter.validate_ghost_host(host)
    assert "SECRET" not in str(error.value)


@pytest.fixture
def proposal(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    result = {"dry_run": True, "proposed": [{"type": "BUY", "symbol": "TEST", "quantity": 1}],
        "cash": 42.5, "accepted": [], "history_verified": False, "rolling_verified": True}
    monkeypatch.setattr(adapter, "run_sync", lambda *a: result)
    return result


def test_review_plan_preserves_financial_proposal_and_private_permissions(proposal, tmp_path):
    destination = tmp_path / "private" / "proposal.json"
    assert adapter.main(["--sync", "--plan-output", str(destination)]) == 0
    data = json.loads(destination.read_text())
    assert data["activities"] == proposal["proposed"] and data["cash"] == 42.5
    assert data["history_verified"] is False and data["rolling_verified"] is True
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.parent.stat().st_mode & 0o777 == 0o700
    assert not {"credentials", "session", "password", "totp", "token"} & set(data)


@pytest.mark.parametrize("mode", ["0", "false", "no", "off", "invalid"])
def test_live_or_invalid_plan_mode_fails_before_sync(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("DRY_RUN", mode)
    monkeypatch.setattr(adapter, "run_sync", lambda *a: pytest.fail("Sync attempted"))
    destination = tmp_path / "proposal.json"
    assert adapter.main(["--sync", "--plan-output", str(destination)]) == 1
    assert not destination.exists()


def test_existing_plan_and_symlink_preserved_before_sync(monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(adapter, "run_sync", lambda *a: pytest.fail("Sync attempted"))
    destination = tmp_path / "existing.json"
    destination.write_bytes(b"PRIVATE ORIGINAL")
    alias = tmp_path / "alias.json"
    alias.symlink_to(destination)
    for path in (destination, alias):
        assert adapter.main(["--sync", "--plan-output", str(path)]) == 1
    assert destination.read_bytes() == b"PRIVATE ORIGINAL"


def test_plan_option_not_available_to_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "read_degiro", lambda *a, **k: pytest.fail("Broker attempted"))
    assert adapter.main(["--read-only", "--from-date", "2026-01-01", "--to-date", "2026-01-02",
        "--output", str(tmp_path / "capture.json"), "--plan-output", str(tmp_path / "plan.json")]) == 1
    assert not list(tmp_path.iterdir())


def test_no_plan_is_persisted_when_simulation_fails(proposal, monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "run_sync", lambda *a: (_ for _ in ()).throw(RuntimeError("blocked")))
    destination = tmp_path / "proposal.json"
    assert adapter.main(["--sync", "--plan-output", str(destination)]) == 1
    assert not destination.exists()


def test_compose_renders_synthetic_configuration_without_network(tmp_path):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for rendering verification")
    environment = {"PATH": os.environ["PATH"], "BW_CLIENTID": "user.synthetic", "BW_CLIENTSECRET": "fake",
        "BW_PASSWORD": "fake", "BW_ITEM_ID": "12345678-1234-4234-8234-123456789abc",
        "GHOST_ACCESS_TOKEN": "fake", "DEGIRO_ACCOUNT_ID": "123", "GHOST_ACCOUNT_ID": "target",
        "GHOST_NETWORK": "synthetic-network", "DEGIRO_MAPPING_PATH": str(tmp_path / "mapping.yaml"),
        "DEGIRO_STATE_PATH": str(tmp_path / "state")}
    result = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", "compose.yaml",
        "config", "--format", "json"], env=environment, capture_output=True, timeout=15, check=True)
    config = json.loads(result.stdout)
    service = config["services"]["degiro-sync"]
    assert service["read_only"] is True and service["user"] == "10001:10001"
    assert service["environment"]["DRY_RUN"] == "1" and service["environment"]["CRON"] == ""
    assert service["environment"]["BW_PASSWORD"] == "fake"
    assert not any(key.startswith("DEGIRO_"+suffix) for key in service["environment"]
                   for suffix in ("USERNAME", "PASSWORD", "TOTP"))
    # Compose versions differ in whether false JSON fields are omitted.
    # Verify the explicit source guard as well as its rendered boolean semantics.
    import yaml
    source = yaml.safe_load(Path("compose.yaml").read_text())["services"]["degiro-sync"]
    assert all(volume["bind"]["create_host_path"] is False for volume in source["volumes"])
    assert all(volume.get("bind", {}).get("create_host_path", False) is False
               for volume in service["volumes"])
    assert service["volumes"][0]["read_only"] is True
    assert config["networks"]["ghostfolio"]["external"] is True
    assert config["networks"]["ghostfolio"]["name"] == "synthetic-network"


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_ghost_account_discovery_is_get_only_private_and_without_broker(monkeypatch, tmp_path, dry_run):
    import requests
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setenv("GHOST_HOST", "https://portfolio.example")
    monkeypatch.setenv("GHOST_TOKEN", "synthetic-bearer")
    monkeypatch.delenv("GHOST_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(adapter, "broker_credentials", lambda: pytest.fail("Broker contacted"))
    calls = []
    def send(self, request, **options):
        calls.append(request)
        assert request.method == "GET" and request.url == "https://portfolio.example/api/v1/account"
        assert options["allow_redirects"] is False and options["verify"] is True
        assert self.trust_env is False
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"accounts": [{"id": "target-uuid", "name": "Test",
            "currency": "EUR", "balance": 42, "unexpected": "private"}]}).encode()
        return response
    monkeypatch.setattr(requests.Session, "send", send)
    destination = tmp_path / "accounts.json"
    assert adapter.main(["--ghost-accounts", "--output", str(destination)]) == 0
    assert len(calls) == 1
    assert json.loads(destination.read_text()) == {"accounts": [
        {"id": "target-uuid", "name": "Test", "currency": "EUR"}]}
    assert destination.stat().st_mode & 0o777 == 0o600


def test_existing_discovery_output_refused_before_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "discover_ghost_accounts", lambda: pytest.fail("Auth attempted"))
    destination = tmp_path / "accounts.json"
    destination.write_bytes(b"original")
    assert adapter.main(["--ghost-accounts", "--output", str(destination)]) == 1
    assert destination.read_bytes() == b"original"


def test_complete_synthetic_community_journey(monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("community_journey", Path("scripts/community_journey.py"))
    journey = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(journey)
    monkeypatch.setenv("COMMUNITY_FIXTURE", str(Path("tests/fixtures/degiro_contract.yaml").resolve()))
    journey.main()
    assert "zero financial writes" in capsys.readouterr().out
