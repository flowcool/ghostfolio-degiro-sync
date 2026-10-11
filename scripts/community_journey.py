"""Run the documented discovery/DRY_RUN journey with synthetic CLI and HTTP only.

Mount this script and the public contract fixture read-only into the runtime image.
No pytest, credentials, network, broker account or production state is needed.
"""
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

import yaml

sys.path.insert(0, str(Path("/app") if Path("/app/degiro_to_ghostfolio.py").is_file() else Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


ITEM = "12345678-1234-4234-8234-123456789abc"
SEED = "JBSWY3DPEHPK3PXP"


def synthetic_contract(path):
    fixture = yaml.safe_load(path.read_text())
    snapshot = {"transactions": fixture["transactions"], "products": fixture["products"],
        "cash_movements": [fixture["cash_movements"][key] for key in
            ("paid_dividend", "dividend_withholding", "trade_commission", "exchange_connection_fee")],
        "update": deepcopy(fixture["current_cash"])}
    snapshot["cash_movements"].append({"id": 110, "type": "TRANSACTION", "productId": 20,
        "description": "Vente 2 TEST", "change": 20, "currency": "USD",
        "date": fixture["transactions"][0]["date"], "valueDate": fixture["transactions"][0]["date"]})
    today = datetime.now(adapter.ZoneInfo("Europe/Zurich")).date()
    shift = today - date(2026, 1, 4)
    for row in snapshot["transactions"] + snapshot["cash_movements"]:
        for key in ("date", "valueDate"):
            if key in row:
                row[key] = (datetime.fromisoformat(row[key]) + shift).isoformat()
        row.setdefault("valueDate", row["date"])
    snapshot["update"]["portfolio"]["value"].append({"id": "20", "name": "positionrow",
        "value": [{"name": "id", "value": "20"}, {"name": "size", "value": 8}]})
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Date", "Heure", "Date de", "Produit", "Code ISIN", "Description",
        "FX", "Mouvements", "", "Solde", "", "ID Ordre"])
    for row in snapshot["cash_movements"]:
        instant, value = datetime.fromisoformat(row["date"]), datetime.fromisoformat(row["valueDate"])
        product = snapshot["products"].get(str(row.get("productId")), {})
        writer.writerow([instant.strftime("%d-%m-%Y"), instant.strftime("%H:%M"),
            value.strftime("%d-%m-%Y"), "Synthetic", product.get("isin", ""), row["description"],
            "", row.get("currency", ""), str(row.get("change", "")).replace(".", ","), "EUR", "0,00",
            str(row.get("orderId") or "")])
    snapshot["statement"] = stream.getvalue()
    return snapshot


def main():
    fixture = Path(os.environ.get("COMMUNITY_FIXTURE", "/journey/degiro_contract.yaml"))
    snapshot = synthetic_contract(fixture)
    destination = {"id": "target-a", "name": "Synthetic", "currency": "EUR", "balance": 12.3}
    opening = {"id": "opening", "accountId": "target-a", "date": "2020-01-01T00:00:00Z",
        "type": "BUY", "currency": "USD", "quantity": 10, "unitPrice": 1, "fee": 0,
        "comment": None, "assetProfile": {"symbol": "TEST", "dataSource": "YAHOO"}}
    vault_calls, http_calls, state_paths = [], [], []
    def cli(command, **options):
        stage = command[1]
        vault_calls.append(stage)
        state_paths.append(Path(options["env"]["BITWARDENCLI_APPDATA_DIR"]))
        assert state_paths[-1].is_dir() and options["timeout"] <= 30
        body = (json.dumps({"id": ITEM, "type": 1, "login": {"username": "synthetic-user",
            "password": "synthetic-password", "totp": SEED}}) if stage == "get"
            else "c2Vzc2lvbg==" if stage == "unlock" else "")
        return subprocess.CompletedProcess(command, 0, body.encode())
    def send(self, request, **options):
        parts = urlsplit(request.url)
        path = parts.path
        http_calls.append((request.method, path))
        assert options["allow_redirects"] is False and options["verify"] is True
        assert self.trust_env is False
        if parts.hostname == "portfolio.example":
            if path.endswith("/auth/anonymous"):
                assert request.method == "POST"
                body = {"authToken": "synthetic-session"}
            else:
                assert request.method == "GET", "Financial write attempted"
                body = ({"accounts": [destination]} if path.endswith("/account") else destination
                    if path.endswith("/account/target-a") else {"count": 1, "activities": [opening]})
        elif path.endswith("/login/totp"):
            assert vault_calls[-1] == "logout" and not any(path.exists() for path in state_paths)
            assert json.loads(request.body)["password"] == "synthetic-password"
            body = {"sessionId": "synthetic-broker-session", "status": 0}
        elif path.endswith("/client"):
            body = {"data": {"intAccount": 123}}
        elif path.endswith("/transactions"):
            body = {"data": snapshot["transactions"]}
        elif path.endswith("/accountoverview"):
            body = {"data": {"cashMovements": snapshot["cash_movements"]}}
        elif path.endswith("/products/info"):
            body = {"data": snapshot["products"]}
        elif "/account/info/" in path:
            body = {"data": {"baseCurrency": "EUR"}}
        elif "/update/" in path:
            body = snapshot["update"]
        elif path.endswith("cashAccountReport/csv"):
            response = adapter.requests.Response()
            response.status_code = 200
            response._content = snapshot["statement"].encode()
            response.encoding = "utf-8"
            return response
        elif "/logout;" in path:
            body = {}
        else:
            raise AssertionError("Unexpected synthetic endpoint")
        response = adapter.requests.Response()
        response.status_code = 200
        response._content = json.dumps(body).encode()
        return response
    def blocked(*args, **kwargs):
        raise AssertionError("Real network forbidden")
    with tempfile.TemporaryDirectory(prefix="community-journey-") as directory:
        root = Path(directory)
        mapping = root / "mapping.yaml"
        mapping.write_text(yaml.safe_dump({"US0378331005": {"symbol": "TEST", "currency": "USD"}}))
        state = root / "state"
        state.mkdir(mode=0o700)
        environment = {"PATH": os.environ.get("PATH", ""), "BW_CLIENTID": "user.synthetic",
            "BW_CLIENTSECRET": "synthetic-api", "BW_PASSWORD": "synthetic-master", "BW_ITEM_ID": ITEM,
            "BW_SERVER": "https://vault.example", "GHOST_HOST": "https://portfolio.example",
            "GHOST_ACCESS_TOKEN": "synthetic-security-token", "GHOST_ACCOUNT_ID": "target-a",
            "DEGIRO_ACCOUNT_ID": "123", "DRY_RUN": "1", "SYNC_MODE": "rolling", "LOOKBACK_DAYS": "90",
            "MAPPING_FILE": str(mapping), "STATE_DIR": str(state)}
        with patch.dict(os.environ, environment, clear=True), patch.object(subprocess, "run", cli), \
                patch.object(adapter.requests.Session, "send", send), \
                patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked):
            assert adapter.main(["--read-only", "--from-date", date.today().isoformat(),
                "--to-date", (date.today() + timedelta(days=1)).isoformat(),
                "--output", str(root / "broker.json")]) == 0
            assert json.loads((root / "broker.json").read_text())["source_account"] == "123"
            assert adapter.main(["--ghost-accounts", "--output", str(root / "accounts.json")]) == 0
            assert json.loads((root / "accounts.json").read_text())["accounts"][0]["id"] == "target-a"
            plan = root / "plan.json"
            assert adapter.main(["--sync", "--plan-output", str(plan)]) == 0
            data = json.loads(plan.read_text())
            assert {row["type"] for row in data["activities"]} == {"SELL", "DIVIDEND", "FEE"}
            assert data["rolling_verified"] and not data["history_verified"] and data["cash"] == 12.3
            assert plan.stat().st_mode & 0o777 == 0o600
            assert not list(state.glob("*.yaml")), "Simulation persisted financial coverage"
            assert vault_calls == ["config", "login", "unlock", "sync", "get", "logout"] * 2
            assert all(method == "GET" or path.endswith("/auth/anonymous") for method, path in http_calls
                       if path.startswith("/api/"))
    print("PASS synthetic community journey: fresh vault, real connector, private discovery, rolling DRY_RUN plan, zero financial writes")


if __name__ == "__main__":
    main()
