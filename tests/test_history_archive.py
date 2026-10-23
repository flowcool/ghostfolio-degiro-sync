"""Synthetic archive CLI scenarios: real pinned actions and bounded HTTP transport."""
import importlib.util
from pathlib import Path


import hashlib
import json
import os
from urllib.parse import urlsplit

import pytest
import requests
import yaml
from degiro_connector.trading.models.credentials import Credentials


def load_archive():
    spec = importlib.util.spec_from_file_location("history_archive", Path(__file__).parents[1] / "scripts/archive_degiro_history.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_boundary_invalid_dates_precede_vault(tmp_path, monkeypatch):
    archive = load_archive()
    monkeypatch.setattr(archive.vault, "broker_credentials", lambda: (_ for _ in ()).throw(AssertionError("Vault reached")))
    output = tmp_path / "capture"
    assert archive.main(["--from-date", "2026-10-02", "--to-date", "2026-10-01", "--output-directory", str(output)]) == 1
    assert not output.exists()


@pytest.fixture
def broker(monkeypatch):
    archive = load_archive()
    for name in ("BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD", "BW_SESSION", "GHOST_TOKEN", "GHOST_ACCESS_TOKEN",
                 "DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    calls, vault_calls, sessions = [], [], []
    replies = {}
    def credentials():
        vault_calls.append(True)
        return Credentials(username="synthetic-user", password="synthetic-password", one_time_password=975310)
    def send(self, request, **kwargs):
        calls.append((request, kwargs))
        path = urlsplit(request.url).path
        kind = ("login" if "/login/" in path else "client" if path == "/pa/secure/client" else
                "transactions" if path.endswith("/transactions") else
                "account_overview" if path.endswith("/accountoverview") else
                "products" if path.endswith("/products/info") else
                "account_info" if "/account/info/" in path else
                "account_update" if "/update/" in path else
                "account_report" if path.endswith("/csv") else "logout")
        default = {"login": b'{"sessionId":"synthetic-session"}', "client": b'{"data":{"intAccount":123}}',
            "transactions": b'{"data":[{"id":0,"productId":42,"price":1.234567890123456789}]}',
            "account_overview": b'{"data":{"cashMovements":[{"id":0,"type":"CASH_FUND_NAV_CHANGE"},{"id":0,"type":"CASH_FUND_TRANSACTION"},null]}}',
            "products": b'{"data":{"42":{"isin":"TEST"}}}',
            "account_info": b'{"data":{"baseCurrency":"EUR"}}',
            "account_update": b'{"portfolio":{},"cashFunds":{},"totalPortfolio":{}}',
            "account_report": b"Date,Amount\n2000-01-01,1.2300\n", "logout": b'{}'}[kind]
        payload = replies.get(kind, default)
        if callable(payload):
            payload = payload(request)
        if isinstance(payload, Exception):
            raise payload
        status, body = payload if isinstance(payload, tuple) else (200, payload)
        response = requests.Response()
        response.status_code, response._content = status, body
        response._content_consumed = True
        response.request, response.url = request, request.url
        response.encoding = "utf-8"
        return response
    monkeypatch.setattr(archive.vault, "broker_credentials", credentials)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    original = archive.degiro.bounded_broker_session
    def session():
        value = original()
        sessions.append(value)
        return value
    monkeypatch.setattr(archive.degiro, "bounded_broker_session", session)
    monkeypatch.setenv("DRY_RUN", "true")
    return archive, calls, replies, vault_calls, sessions


def arguments(output, *extra):
    return ["--from-date", "2000-01-01", "--to-date", "2000-01-04", "--window-days", "3", "--output-directory", str(output), *extra]


def index_at(output):
    return yaml.safe_load((output / "index.yaml").read_bytes())


def test_preservation_exact_bytes_and_boundary_one_login(broker, tmp_path):
    archive, calls, replies, vault_calls, sessions = broker
    output = tmp_path / "archive"
    assert archive.main(arguments(output, "--report-country", "fr", "--report-language", "fr")) == 0
    index = index_at(output)
    assert index["status"] == "requests_finished"
    assert index["history_completeness_verified"] is False
    assert index["import_status"] == "archive_not_importable"
    assert index["source_account"] == "123"
    assert len(index["steps"]) == 8
    assert len(vault_calls) == len(sessions) == 1
    assert sum("/login/" in r.url for r, _ in calls) == 1
    assert sum("/logout;" in r.url for r, _ in calls) == 1
    assert all(r.url.startswith("https://trader.degiro.nl/") for r, _ in calls)
    assert all(k["timeout"] == (10, 30) and k["stream"] is False and k["verify"] is True for _, k in calls)
    windows = []
    for step in index["steps"].values():
        body = (output / step["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == step["sha256"]
        assert step["byte_count"] == len(body)
        assert step["source_account"] == "123" and step["http_status"] == 200
        if step["kind"] == "transactions":
            assert b"1.234567890123456789" in body
            windows.append((step["from_date"], step["to_date"]))
        if step["kind"] == "account_overview":
            assert json.loads(body)["data"]["cashMovements"] == [{"id":0,"type":"CASH_FUND_NAV_CHANGE"},{"id":0,"type":"CASH_FUND_TRANSACTION"},None]
        assert (output / step["file"]).stat().st_mode & 0o777 == 0o600
        assert (output / step["file"]).stat().st_uid == os.geteuid()
    assert windows == [("2000-01-01", "2000-01-03"), ("2000-01-03", "2000-01-04")]
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / "index.yaml").stat().st_mode & 0o777 == 0o600
    all_bytes = b"".join(p.read_bytes() for p in output.iterdir())
    assert all(s not in all_bytes for s in (b"synthetic-user", b"synthetic-password", b"synthetic-session", b"975310", b"https://"))
    assert sessions[0].degiro_evidence == []


@pytest.mark.parametrize("body,reason", [
    (b'{"data":[{"password":"hidden"},{"password":null}]}', "credential_key"),
    (b'{"data":[{"SessionId":"hidden"}]}', "credential_key"),
    (b'{"data":"synthetic-password"}', "credential_material"),
    (b'{"data":"synthetic-\\u0070assword","data":[]}', "credential_material"),
    (b'{"data": [}', "unparseable_json"),
    (b'{"data":"\xff"}', "invalid_encoding"),
    (b'{"data":NaN}', "unparseable_json"),
    (b'{"data":' + b'[' * 70 + b'0' + b']' * 70 + b'}', "json_depth_limit"),
])
def test_retention_unsafe_body_never_published(broker, tmp_path, body, reason):
    archive, calls, replies, _, sessions = broker
    replies["account_overview"] = body
    output = tmp_path / "partial"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed" and index["logout"] == "finished"
    steps = list(index["steps"].values())
    assert len(steps) == 2
    assert (output / steps[0]["file"]).read_bytes().startswith(b'{"data":[')
    assert steps[1]["refusal_reason"] == reason
    assert steps[1]["sha256"] == hashlib.sha256(body).hexdigest()
    assert steps[1]["byte_count"] == len(body)
    assert "file" not in steps[1]
    assert len(list(output.glob("*.json"))) == 1
    assert sessions[0].degiro_evidence == []
    assert len(calls) == 5  # login, discovery, first history pair, logout; no retry.


@pytest.mark.parametrize("failure", [(503,b'password=DO_NOT_RETAIN'), (302,b'redirect'), (405,b'maintenance'), requests.Timeout("SENSITIVE_URL")])
def test_retention_failed_http_or_timeout_stops_without_retry(broker, tmp_path, capsys, failure):
    archive, calls, replies, _, _ = broker
    replies["account_overview"] = failure
    output = tmp_path / "failed"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed" and index["logout"] == "finished"
    assert len(list(output.glob("*.json"))) == 1
    assert len(calls) == 5
    assert "SENSITIVE_URL" not in capsys.readouterr().err
    assert b"DO_NOT_RETAIN" not in (output / "index.yaml").read_bytes()


@pytest.mark.parametrize("scope", ["existing", "symlink", "parent_symlink", "live", "budget", "window", "locale"])
def test_boundary_refuses_before_credentials(broker, tmp_path, monkeypatch, scope):
    archive, calls, _, vault_calls, _ = broker
    output = tmp_path / "new"
    extra = []
    if scope == "existing":
        output.mkdir()
        (output / "sentinel").write_bytes(b"unchanged")
    elif scope == "symlink":
        output.symlink_to(tmp_path / "missing")
    elif scope == "parent_symlink":
        link = tmp_path / "link"
        link.symlink_to(tmp_path, target_is_directory=True)
        output = link / "new"
    elif scope == "live":
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("TZ", "Europe/Zurich")
    elif scope == "budget":
        extra = ["--from-date", "2000-01-01", "--to-date", "2026-10-23", "--window-days", "2"]
    elif scope == "window":
        extra = ["--window-days", "367"]
    elif scope == "locale":
        extra = ["--report-country", "fr"]
    assert archive.main(arguments(output, *extra)) == 1
    assert calls == vault_calls == []
    if scope == "existing":
        assert (output / "sentinel").read_bytes() == b"unchanged"


def test_limits_product_ids_skip_invalid_after_preservation(broker, tmp_path):
    archive, calls, replies, _, _ = broker
    replies["transactions"] = b'{"data":[{"productId":0},{"productId":true},{"productId":null},{"productId":"bad"},{"productId":"42"},{"productId":42}]}'
    output = tmp_path / "products"
    assert archive.main(arguments(output)) == 0
    index = index_at(output)
    steps = list(index["steps"].values())
    assert steps[0]["invalid_product_ids_skipped"] == 4
    assert (output / steps[0]["file"]).read_bytes() == replies["transactions"]
    product_requests = [r for r, _ in calls if "/products/info" in r.url]
    assert len(product_requests) == 1
    assert json.loads(product_requests[0].body) == [42]


@pytest.mark.parametrize("limit", ["body", "total", "ids", "requests"])
def test_limits_preserve_previous_evidence(broker, tmp_path, monkeypatch, limit):
    archive, calls, replies, _, sessions = broker
    if limit == "body":
        monkeypatch.setattr(archive, "MAX_BODY_BYTES", 100)
        replies["account_overview"] = b'{"data": "' + b'x' * 101 + b'"}'
    elif limit == "total":
        monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", 100)
    else:
        replies["transactions"] = b'{"data":[{"productId":42},{"productId":43}]}'
        monkeypatch.setattr(archive, "MAX_PRODUCT_IDS" if limit == "ids" else "MAX_PRODUCT_REQUESTS", 1 if limit == "ids" else 0)
    output = tmp_path / "limited"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed" and index["logout"] == "finished"
    assert len(list(output.glob("*.json"))) >= 1
    assert not any("/products/info" in r.url for r, _ in calls)
    assert sessions[0].degiro_evidence == []


def test_retention_vendor_catches_storage_error_but_cannot_report_success(broker, tmp_path, monkeypatch):
    archive, calls, _, _, _ = broker
    original = archive.publish
    def fail(fd, name, body, replace=False):
        if name == "response-0002.json":
            raise OSError("SECRET_STORAGE_PATH")
        return original(fd, name, body, replace)
    monkeypatch.setattr(archive, "publish", fail)
    output = tmp_path / "storage"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed"
    steps = list(index["steps"].values())
    assert steps[1]["refusal_reason"] == "archive_storage_or_transport_failure"
    assert (output / steps[0]["file"]).exists()
    assert "SECRET_STORAGE_PATH" not in (output / "index.yaml").read_text()
    assert len(calls) == 5


@pytest.mark.parametrize("point", ["intent", "body_fsync", "index_after_body"])
def test_retention_crash_points_leave_pending_or_orphan_evidence(broker, tmp_path, monkeypatch, point):
    archive, calls, _, _, _ = broker
    original_publish, original_fsync = archive.publish, archive.os.fsync
    crashed = False
    def publish(fd, name, body, replace=False):
        nonlocal crashed
        index = yaml.safe_load(body) if name == "index.yaml" else None
        steps = list(index.get("steps", {}).values()) if index else []
        if not crashed and ((point == "intent" and steps and steps[-1]["status"] == "pending") or
                            (point == "index_after_body" and steps and steps[-1]["status"] == "retained")):
            crashed = True
            if point == "intent":
                original_publish(fd, name, body, replace)
            raise KeyboardInterrupt("synthetic process death")
        return original_publish(fd, name, body, replace)
    def fsync(fd):
        nonlocal crashed
        if point == "body_fsync" and not crashed and calls and "/transactions" in calls[-1][0].url:
            crashed = True
            raise KeyboardInterrupt("synthetic process death")
        return original_fsync(fd)
    monkeypatch.setattr(archive, "publish", publish)
    monkeypatch.setattr(archive.os, "fsync", fsync)
    output = tmp_path / "crash"
    with pytest.raises(KeyboardInterrupt):
        archive.main(arguments(output))
    index = index_at(output)
    assert index["status"] == "pending"
    step = list(index["steps"].values())[-1]
    assert step["status"] == "pending" and "file" not in step
    if point == "intent":
        assert not list(output.glob("*.json"))
    else:
        assert any(p.name != "index.yaml" for p in output.iterdir())
    assert archive.main(arguments(output)) == 1  # No resume or overwrite.


def test_retention_publication_never_replaces_existing_response(broker, tmp_path, monkeypatch):
    archive, _, _, _, _ = broker
    original = archive.publish
    def collision(fd, name, body, replace=False):
        if name == "response-0001.json":
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
            os.write(descriptor, b"prior evidence")
            os.close(descriptor)
        return original(fd, name, body, replace)
    monkeypatch.setattr(archive, "publish", collision)
    output = tmp_path / "collision"
    assert archive.main(arguments(output)) == 1
    assert (output / "response-0001.json").read_bytes() == b"prior evidence"
    assert index_at(output)["status"] == "failed"


def test_boundary_direct_credentials_remain_rejected(tmp_path, monkeypatch):
    archive = load_archive()
    monkeypatch.setenv("DEGIRO_USERNAME", "")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setattr(archive.vault, "vault_broker_credentials", lambda: pytest.fail("Vault reached"))
    assert archive.main(arguments(tmp_path / "direct")) == 1


@pytest.mark.parametrize("body", [b'{"data":{}}', b'{"unexpected":[]}', b'{"data":[null,"unknown",{}, {"id":0,"type":"FUTURE_TYPE"}]}'])
def test_preservation_missing_collections_and_unknown_rows(broker, tmp_path, body):
    archive, _, replies, _, _ = broker
    replies["account_overview"] = body
    output = tmp_path / "readable"
    assert archive.main(arguments(output)) == 0
    step = list(index_at(output)["steps"].values())[1]
    assert (output / step["file"]).read_bytes() == body


@pytest.mark.parametrize("body", [b"Date,sessionId\n2000-01-01,hidden\n", b"Date,Amount\n2000-01-01,\xff\n", b"Date,Description\n2000-01-01,synthetic-password\n"])
def test_retention_csv_refuses_unsafe_body(broker, tmp_path, body):
    archive, calls, replies, _, _ = broker
    replies["account_report"] = body
    output = tmp_path / "csv"
    assert archive.main(arguments(output, "--report-country", "fr", "--report-language", "fr")) == 1
    step = list(index_at(output)["steps"].values())[-1]
    assert step["kind"] == "account_report" and step["status"] == "failed"
    assert step["byte_count"] == len(body) and "file" not in step
    assert not list(output.glob("*.csv"))


@pytest.mark.parametrize("behavior", ["no_response", "two_responses"])
def test_retention_collection_requires_exactly_one_response(broker, tmp_path, monkeypatch, behavior):
    from degiro_connector.trading.actions.action_get_transactions_history import ActionGetTransactionsHistory
    archive, calls, _, _, _ = broker
    original = ActionGetTransactionsHistory.get_transactions_history
    def action(**kwargs):
        if behavior == "no_response":
            return {"data": []}
        result = original(**kwargs)
        original(**kwargs)  # Vendor swallows the archive's refusal of the second dispatch.
        return result  # A plausible return value must not hide the sticky failure.
    monkeypatch.setattr(ActionGetTransactionsHistory, "get_transactions_history", action)
    output = tmp_path / "response_count"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed"
    assert len(index["steps"]) == 1
    assert sum("/transactions" in r.url for r, _ in calls) == (behavior == "two_responses")


def test_preservation_current_portfolio_references_receive_metadata(broker, tmp_path):
    archive, calls, replies, _, _ = broker
    replies["account_update"] = b'{"portfolio":{"value":[{"id":"77","value":[{"name":"id","value":"77"}]}]},"cashFunds":{},"totalPortfolio":{}}'
    output = tmp_path / "holdings"
    assert archive.main(arguments(output)) == 0
    request = next(r for r, _ in calls if "/products/info" in r.url)
    assert json.loads(request.body) == [42, 77]


def test_retention_logout_failure_does_not_claim_finished(broker, tmp_path):
    archive, _, replies, _, _ = broker
    replies["logout"] = (500, b"DO_NOT_RETAIN_LOGOUT")
    output = tmp_path / "logout"
    assert archive.main(arguments(output)) == 1
    index = index_at(output)
    assert index["status"] == "failed" and index["logout"] == "failed"
    assert b"DO_NOT_RETAIN_LOGOUT" not in b"".join(p.read_bytes() for p in output.iterdir())



def test_retention_intent_storage_failure_stops_dispatch_and_still_logs_out(broker, tmp_path, monkeypatch):
    archive, calls, _, _, _ = broker
    original = archive.save_index
    failed = False
    def save(fd, index):
        nonlocal failed
        steps = list(index["steps"].values())
        if not failed and len(steps) == 2 and steps[-1]["status"] == "pending":
            failed = True
            raise OSError("synthetic full disk")
        return original(fd, index)
    monkeypatch.setattr(archive, "save_index", save)
    output = tmp_path / "intent_storage"
    assert archive.main(arguments(output)) == 1
    assert len(calls) == 4
    assert "/logout;" in calls[-1][0].url
    assert index_at(output)["logout"] == "finished"
    assert len(list(output.glob("*.json"))) == 1



def test_preservation_http_decoded_bytes_not_compressed_wire(broker, tmp_path, monkeypatch):
    import gzip
    import io
    import urllib3
    archive, _, _, _, _ = broker
    original = requests.adapters.HTTPAdapter.send
    body = b'{"data":[{"id":0,"price":1.234567890123456789}]}'
    compressed = gzip.compress(body)
    def send(self, request, **kwargs):
        response = original(self, request, **kwargs)
        if "/transactions" in request.url:
            response._content, response._content_consumed = False, False
            response.raw = urllib3.response.HTTPResponse(body=io.BytesIO(compressed),
                headers={"content-encoding": "gzip"}, preload_content=False)
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    output = tmp_path / "decoded"
    assert archive.main(arguments(output)) == 0
    step = list(index_at(output)["steps"].values())[0]
    assert (output / step["file"]).read_bytes() == body
    assert step["sha256"] == hashlib.sha256(body).hexdigest()
    assert step["byte_count"] != len(compressed)


def test_limits_metadata_batches_at_most_one_hundred_ids(broker, tmp_path):
    archive, calls, replies, _, _ = broker
    replies["transactions"] = json.dumps({"data":[{"productId":n} for n in range(1,202)]}).encode()
    output = tmp_path / "batches"
    assert archive.main(arguments(output)) == 0
    batches = [json.loads(r.body) for r, _ in calls if "/products/info" in r.url]
    assert [len(batch) for batch in batches] == [100,100,1]
    assert {n for batch in batches for n in batch} == set(range(1,202))



def test_retention_no_retry_after_vendor_swallows_transport_timeout(broker, tmp_path, monkeypatch):
    from degiro_connector.trading.actions.action_get_transactions_history import ActionGetTransactionsHistory
    archive, calls, replies, _, _ = broker
    replies["transactions"] = requests.Timeout("SYNTHETIC")
    original = ActionGetTransactionsHistory.get_transactions_history
    def action(**kwargs):
        original(**kwargs)
        original(**kwargs)
        return {"data": []}
    monkeypatch.setattr(ActionGetTransactionsHistory, "get_transactions_history", action)
    output = tmp_path / "no_retry"
    assert archive.main(arguments(output)) == 1
    assert sum("/transactions" in r.url for r, _ in calls) == 1
    assert index_at(output)["logout"] == "finished"


def test_limits_unrepresentable_product_id_is_skipped_after_source_publication(broker, tmp_path):
    archive, _, replies, _, _ = broker
    replies["transactions"] = json.dumps({"data":[{"productId":"9" * 5000}]}).encode()
    output = tmp_path / "bad_identity"
    assert archive.main(arguments(output)) == 0
    step = list(index_at(output)["steps"].values())[0]
    assert step["invalid_product_ids_skipped"] == 1
    assert (output / step["file"]).read_bytes() == replies["transactions"]



def synthetic_archive(tmp_path, responses):
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    steps = {}
    for number, (kind, body) in enumerate(responses, 1):
        identity = f"response-{number:04d}"
        filename = identity + (".csv" if kind == "account_report" else ".json")
        (root / filename).write_bytes(body)
        (root / filename).chmod(0o600)
        steps[identity] = {"id": identity, "kind": kind, "status": "retained", "file": filename,
            "http_status": 200, "responses_seen": 1, "requests_dispatched": 1,
            "source_account": "123", "from_date": "2000-01-01", "to_date": "2000-01-03",
            "byte_count": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    index = {"version": 1, "status": "requests_finished", "steps": steps,
        "history_completeness_verified": False, "import_status": "archive_not_importable"}
    (root / "index.yaml").write_text(yaml.safe_dump(index))
    (root / "index.yaml").chmod(0o600)
    return root


def inspect_arguments(root, output):
    return ["--inspect-directory", str(root), "--index-sha256", hashlib.sha256((root / "index.yaml").read_bytes()).hexdigest(),
            "--output-directory", str(output)]


def test_exclusions_conserve_rows_overlap_and_preserve_inputs(tmp_path, monkeypatch):
    archive = load_archive()
    body = b'{"data":{"cashMovements":[{"id":0,"type":"CASH_FUND_NAV_CHANGE"},{"id":0,"type":"CASH_FUND_TRANSACTION"},{"type":"TRANSACTION"},{"type":"FUTURE_TYPE"},null,{}]}}'
    root = synthetic_archive(tmp_path, [("account_overview", body), ("account_overview", body)])
    before = {p.name:p.read_bytes() for p in root.iterdir()}
    monkeypatch.setattr(archive.vault, "broker_credentials", lambda: pytest.fail("Credentials accessed"))
    monkeypatch.setattr(archive.degiro, "bounded_broker_session", lambda: pytest.fail("Broker accessed"))
    monkeypatch.setenv("DRY_RUN", "invalid-unused-in-offline-inspection")
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    assert report["import_status"] == "archive_not_importable"
    assert report["history_completeness_verified"] is False
    assert report["financial_writes"] == 0
    assert report["index_sha256"] == hashlib.sha256(before["index.yaml"]).hexdigest()
    assert len(report["responses"]) == 2
    for response in report["responses"].values():
        assert response["row_count"] == 6
        assert response["classifications"] == {"excluded_legacy":2,"malformed":2,"unknown":1,"unassessed":1}
        assert sum(response["type_counts"].values()) == 6
        assert [r["offset"] for r in response["rows"]] == [f"/data/cashMovements/{i}" for i in range(6)]
    assert before == {p.name:p.read_bytes() for p in root.iterdir()}
    assert (output / "report.yaml").stat().st_mode & 0o777 == 0o600



def rewrite_index(root, mutate):
    index = index_at(root)
    mutate(index)
    (root / "index.yaml").write_text(yaml.safe_dump(index))


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "hash_mismatch"), ("size", "size_mismatch"),
    ("traversal", "unsafe_or_duplicate_response_path"), ("absolute", "unsafe_or_duplicate_response_path"),
    ("symlink", "unreadable_response"), ("hardlink", "unsafe_private_file"),
    ("public", "unsafe_private_file"), ("directory", "unsafe_private_file"),
    ("fifo", "unsafe_private_file"), ("missing", "unreadable_response"),
    ("duplicate_json", "ambiguous_duplicate_json_key"), ("unreadable", "unparseable_json"),
])
def test_exclusions_untrusted_response_never_adopted(tmp_path, mutation, reason):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("transactions", b'{"data":[{"buysell":"B"}]}')])
    body = root / "response-0001.json"
    if mutation == "hash":
        body.write_bytes(b'{"data":[{"buysell":"S"}]}')
    elif mutation in ("size", "traversal", "absolute"):
        def mutate(index):
            step = index["steps"]["response-0001"]
            if mutation == "size": step["byte_count"] += 1
            else: step["file"] = "../outside.json" if mutation == "traversal" else str(body)
        rewrite_index(root, mutate)
    elif mutation in ("symlink", "hardlink"):
        outside = tmp_path / "outside.json"
        body.rename(outside)
        if mutation == "symlink": body.symlink_to(outside)
        else: os.link(outside, body)
    elif mutation == "public":
        body.chmod(0o644)
    elif mutation in ("directory", "fifo", "missing"):
        body.unlink()
        if mutation == "directory": body.mkdir(mode=0o700)
        elif mutation == "fifo": os.mkfifo(body, mode=0o600)
    else:
        raw = b'{"data":[],"data":[{"buysell":"B"}]}' if mutation == "duplicate_json" else b'{"data":['
        body.write_bytes(raw)
        def mutate(index):
            index["steps"]["response-0001"].update(byte_count=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        rewrite_index(root, mutate)
    output = tmp_path / "diagnostics"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    result = report["responses"]["response-0001"]
    assert reason in result["findings"]
    assert result["rows"] == [] and result["row_count"] == 0
    assert report["import_status"] == "archive_not_importable"


def test_exclusions_partial_intents_refusals_and_orphans(tmp_path):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("transactions", b'{"data":[]}')])
    (root / "orphan.json").write_bytes(b'not adopted')
    (root / ".pending-synthetic").write_bytes(b'not adopted either')
    def mutate(index):
        index["status"] = "failed"
        index["steps"]["response-0002"] = {"id":"response-0002","kind":"account_overview","status":"pending"}
        index["steps"]["response-0003"] = {"id":"response-0003","kind":"account_report","status":"failed",
            "http_status":503,"byte_count":15,"sha256":"a"*64,"refusal_reason":"http_failure"}
    rewrite_index(root, mutate)
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    assert report["unindexed_files"] == [".pending-synthetic", "orphan.json"]
    assert report["responses"]["response-0002"]["findings"] == ["pending_intent", "body_unavailable"]
    assert report["responses"]["response-0003"]["findings"] == ["failed_or_refused_step", "body_unavailable"]
    assert "collection_not_finished" in report["findings"]
    assert report["responses"]["response-0003"]["row_count"] == 0


@pytest.mark.parametrize("mutation", ["bad_hash", "index_symlink", "index_hardlink", "index_public", "index_alias", "index_duplicates", "source_symlink", "overlap", "output_exists", "mixed_options"])
def test_exclusions_refuse_unsafe_index_or_destination_preserving_inputs(tmp_path, mutation, capsys):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("transactions", b'{"data":[]}')])
    output = tmp_path / "report"
    if mutation == "index_alias":
        (root / "index.yaml").write_bytes(b'version: 1\nsteps: &steps {}\nother: *steps\n')
    elif mutation == "index_duplicates":
        with (root / "index.yaml").open('ab') as stream: stream.write(b'version: 1\n')
    elif mutation in ("index_symlink", "index_hardlink"):
        outside = tmp_path / "outside.yaml"
        (root / "index.yaml").rename(outside)
        if mutation == "index_symlink": (root / "index.yaml").symlink_to(outside)
        else: os.link(outside, root / "index.yaml")
    elif mutation == "index_public":
        (root / "index.yaml").chmod(0o644)
    elif mutation == "source_symlink":
        link = tmp_path / "source-link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif mutation == "overlap":
        output = root / "report"
    elif mutation == "output_exists":
        output.mkdir()
        (output / "sentinel").write_bytes(b'keep')
    before = {p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    args = inspect_arguments(root, output)
    if mutation == "bad_hash": args[3] = "0"*64
    elif mutation == "mixed_options": args.extend(["--from-date","2000-01-01"])
    assert archive.main(args) == 1
    assert before == {p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert not (output / "report.yaml").exists()
    assert "outside.yaml" not in capsys.readouterr().err


def test_exclusions_metadata_csv_and_empty_envelopes_are_unassessed(tmp_path):
    archive = load_archive()
    responses = [
        ("transactions", b'{"data":[{"buysell":"B"},{"buysell":"S"},{"buysell":false}]}'),
        ("products", b'{"data":{"42":{"isin":"TEST"},"bad":null}}'),
        ("account_info", b'{"data":{"baseCurrency":"EUR"}}'),
        ("account_update", b'{"portfolio":{"value":[{},null]},"cashFunds":{"value":[]},"totalPortfolio":{"value":[{}]}}'),
        ("account_report", b'Date,Description\n2000-01-01,"line one\nline two"\n2000-01-02\n'),
        ("account_overview", b'{"data":{}}'),
        ("transactions", b'{"data":[]}')]
    root = synthetic_archive(tmp_path, responses)
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    results = list(report["responses"].values())
    assert [r["row_count"] for r in results] == [3,2,1,3,2,0,0]
    assert results[0]["classifications"]["unassessed"] == 2
    assert results[1]["rows"][0]["offset"] == "/data/42"
    assert results[3]["rows"][-1]["offset"] == "/totalPortfolio/value/0"
    assert results[4]["rows"][0]["physical_line_end"] == 3
    assert results[4]["rows"][1]["classification"] == "malformed"
    assert results[5]["findings"] == ["missing_or_malformed_collection"]
    assert results[6]["findings"] == []
    for row in results:
        assert sum(row["classifications"].values()) == row["row_count"] == len(row["rows"])



def test_exclusions_actual_capture_then_inspection_cannot_dispatch(broker, tmp_path, monkeypatch):
    from ghostfolio_degiro_sync import accounting, ghostfolio
    archive, calls, _, vault_calls, _ = broker
    root = tmp_path / "capture"
    assert archive.main(arguments(root, "--report-country", "fr", "--report-language", "fr")) == 0
    before = {p.name:(p.read_bytes(), p.stat().st_mode) for p in root.iterdir()}
    counts = (len(calls),len(vault_calls))
    def forbidden(*args, **kwargs):
        pytest.fail("Offline inspection called a live or accounting entry point")
    monkeypatch.setattr(archive.vault, "broker_credentials", forbidden)
    monkeypatch.setattr(archive.degiro, "bounded_broker_session", forbidden)
    monkeypatch.setattr(accounting, "check_api_import_format", forbidden)
    monkeypatch.setattr(accounting, "merge_history", forbidden)
    monkeypatch.setattr(ghostfolio, "ghost_transport", forbidden)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", forbidden)
    output = tmp_path / "inspection"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    assert len(report["responses"]) == 8
    assert all(row["verification"] == "hash_verified" for row in report["responses"].values())
    assert sum(row["classifications"]["excluded_legacy"] for row in report["responses"].values()) == 4
    assert before == {p.name:(p.read_bytes(),p.stat().st_mode) for p in root.iterdir()}
    assert counts == (len(calls),len(vault_calls))
    assert report["inspection_status"] == "findings_detected"


@pytest.mark.parametrize("raw", [b'version: 1\nsteps: !!python/object:unknown {}', b'version: [', b'\xff', b'{}'])
def test_exclusions_malformed_index_refused(tmp_path, raw):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [])
    (root / "index.yaml").write_bytes(raw)
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 1
    assert (root / "index.yaml").read_bytes() == raw
    assert not output.exists()


def test_exclusions_no_findings_still_grants_no_import_permission(tmp_path):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("transactions", b'{"data":[{"buysell":"B"},{"buysell":"S"}]}')])
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    assert report["inspection_status"] == "unassessed_only"
    assert report["import_status"] == "archive_not_importable"
    assert report["responses"]["response-0001"]["classifications"] == {
        "excluded_legacy":0,"unknown":0,"malformed":0,"unassessed":2}



def test_exclusions_duplicate_row_keys_do_not_hide_other_locatable_rows(tmp_path):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("account_overview",
        b'{"data":{"cashMovements":[{"type":"TRANSACTION","type":"FUTURE"},{"type":"CASH_FUND_NAV_CHANGE"},{"type":"CASH_TRANSACTION"}]}}')])
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    response = report["responses"]["response-0001"]
    assert response["row_count"] == 3
    assert response["classifications"] == {"excluded_legacy":1,"malformed":1,"unknown":0,"unassessed":1}
    assert response["rows"][0]["reason"] == "ambiguous_duplicate_row_keys"



def test_exclusions_unrelated_duplicate_keys_do_not_hide_collection(tmp_path):
    archive = load_archive()
    root = synthetic_archive(tmp_path, [("transactions", b'{"other":1,"other":2,"data":[{"buysell":"B"}]}')])
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    assert report["responses"]["response-0001"]["row_count"] == 1



def test_exclusions_large_csv_record_remains_locatable(tmp_path):
    archive = load_archive()
    body = b'Date,Description\n2000-01-01,' + b'x' * 140000 + b'\n'
    root = synthetic_archive(tmp_path, [("account_report", body)])
    output = tmp_path / "report"
    assert archive.main(inspect_arguments(root, output)) == 0
    report = yaml.safe_load((output / "report.yaml").read_bytes())
    response = report["responses"]["response-0001"]
    assert response["row_count"] == 1
    assert response["findings"] == []
