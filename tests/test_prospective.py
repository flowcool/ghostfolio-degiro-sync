"""Account-bound prospective evidence; synthetic private captures only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from types import SimpleNamespace
import csv
import io
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter


MAPPING = {"US0378331005": "TEST"}
QUOTES = {"TEST": "USD"}
CUTOVER = "2025-12-31T12:00:00+00:00"


def private_file(path, content):
    path.write_bytes(content)
    path.chmod(0o600)
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    fixture = yaml.safe_load((Path(__file__).parent / "fixtures/degiro_contract.yaml").read_text())
    broker = {"source_account": "123", "account_info": {"baseCurrency": "EUR"},
        "transactions": [], "cash_movements": [], "products": fixture["products"],
        "update": deepcopy(fixture["current_cash"]),
        "from_date": "2025-12-31", "to_date": "2025-12-31",
        "fetch_started_at": "2025-12-31T11:59:58+00:00", "fetched_at": CUTOVER}
    broker["update"]["portfolio"]["value"].append({"id": "20", "name": "positionrow",
        "value": [{"name": "id", "value": "20"}, {"name": "size", "value": 10}]})
    account = {"id": "target-a", "currency": "EUR", "balance": 12.3}
    row = {"id": "opening", "accountId": "target-a", "date": "2020-01-01T00:00:00Z",
        "type": "BUY", "currency": "USD", "quantity": 10, "unitPrice": 1,
        "fee": 0, "comment": None, "assetProfile": {"symbol": "TEST", "dataSource": "YAHOO"}}
    destination = {"account": account, "captured_at": "2025-12-31T11:59:59+00:00",
        "activities": {"count": 1, "activities": [row]}}
    manifest = {"version": 1, "source_account": "123", "target_account": "target-a",
        "cutover": CUTOVER, "basis_status": "unverified",
        "mapping_sha256": adapter.evidence_digest({"mapping": MAPPING, "quote_currencies": QUOTES}),
        "opening": {}}
    for name, capture in (("broker", broker), ("destination", destination)):
        path = tmp_path / (name + ".json")
        digest = private_file(path, json.dumps(capture).encode())
        manifest["opening"][name] = {"path": path.name, "sha256": digest}
    path = tmp_path / "manifest.yaml"
    digest = private_file(path, yaml.safe_dump(manifest).encode())
    result = adapter.load_prospective_evidence(path, digest)
    return result, path, digest


def opening_context(evidence, mapping=None):
    return adapter.prospective_opening_context(evidence,
        {"source_account": "123", "target_account": "target-a"},
        MAPPING if mapping is None else mapping, QUOTES)


def test_verified_opening_preserves_history_and_separates_basis(evidence):
    loaded, path, digest = evidence
    before = path.read_bytes()
    context = opening_context(loaded)
    assert context["quantities"] == {("target-a", "TEST"): 10}
    assert set(context["protected"]) == {"opening"}
    assert context["cash"] == 12.3 and context["basis_status"] == "unverified"
    assert path.read_bytes() == before
    assert adapter.load_prospective_evidence(path, digest) == loaded


@pytest.mark.parametrize("change", ["quantity", "cash", "source", "target", "mapping",
    "unit", "missing_product", "capture_gap", "concurrent_source", "concurrent_target", "target_currency"])
def test_unproved_opening_is_refused(evidence, change):
    loaded, unused_path, unused_digest = evidence
    broker = loaded["captures"]["broker"]
    destination = loaded["captures"]["destination"]
    if change == "quantity":
        broker["update"]["portfolio"]["value"][-1]["value"][-1]["value"] = 9
    elif change == "cash":
        destination["account"]["balance"] = None
    elif change == "source":
        loaded["manifest"]["source_account"] = "456"
    elif change == "target":
        loaded["manifest"]["target_account"] = "other"
    elif change == "mapping":
        loaded["manifest"]["mapping_sha256"] = "0" * 64
    elif change == "unit":
        broker["products"]["20"]["contractSize"] = 100
    elif change == "missing_product":
        broker["products"].clear()
    elif change == "capture_gap":
        destination["captured_at"] = "2025-12-31T12:00:01Z"
    elif change == "target_currency":
        destination["activities"]["activities"][0]["currency"] = "EUR"
    elif change == "concurrent_source":
        broker["transactions"] = [{"date": "2025-12-31T11:59:59Z"}]
    else:
        destination["activities"]["activities"][0]["date"] = "2025-12-31T11:59:59Z"
    with pytest.raises(RuntimeError):
        opening_context(loaded)


def test_changed_public_or_symlink_evidence_refused(evidence, tmp_path):
    unused_loaded, path, digest = evidence
    alias = tmp_path / "alias.yaml"
    alias.symlink_to(path)
    with pytest.raises(RuntimeError):
        adapter.load_prospective_evidence(alias, digest)
    path.chmod(0o644)
    with pytest.raises(RuntimeError):
        adapter.load_prospective_evidence(path, digest)
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="Changed"):
        adapter.load_prospective_evidence(path, digest)


def test_changed_bound_capture_refused(evidence):
    unused_loaded, path, digest = evidence
    capture = path.parent / "broker.json"
    before = capture.read_bytes()
    capture.write_bytes(before + b"\n")
    with pytest.raises(RuntimeError, match="Changed"):
        adapter.load_prospective_evidence(path, digest)
    assert capture.read_bytes() == before + b"\n"


def test_duplicate_manifest_key_refused(evidence):
    unused_loaded, path, unused_digest = evidence
    digest = private_file(path, path.read_bytes() + b"version: 1\n")
    with pytest.raises(RuntimeError, match="Duplicate"):
        adapter.load_prospective_evidence(path, digest)


def cash_statement(snapshot):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Date", "Heure", "Date de", "Produit", "Code ISIN", "Description",
        "FX", "Mouvements", "", "Solde", "", "ID Ordre"])
    for row in snapshot["cash_movements"]:
        dt = datetime.fromisoformat(row["date"])
        value = datetime.fromisoformat(row["valueDate"])
        product = snapshot["products"].get(str(row.get("productId")), {})
        writer.writerow([dt.strftime("%d-%m-%Y"), dt.strftime("%H:%M"),
            value.strftime("%d-%m-%Y"), "Synthetic", product.get("isin", ""),
            row["description"], "", row.get("currency", ""),
            str(row["change"]).replace(".", ",") if row.get("change") is not None else "",
            "EUR", "0,00", str(row.get("orderId") or "")])
    return stream.getvalue()


@pytest.fixture
def prospective_account(evidence, tmp_path):
    loaded, manifest_path, digest = evidence
    fixture = yaml.safe_load((Path(__file__).parent / "fixtures/degiro_contract.yaml").read_text())
    snapshot = deepcopy(loaded["captures"]["broker"])
    snapshot["transactions"] = fixture["transactions"]
    snapshot["cash_movements"] = [fixture["cash_movements"][name] for name in (
        "paid_dividend", "dividend_withholding", "trade_commission", "exchange_connection_fee")]
    for row in snapshot["cash_movements"]:
        row.setdefault("valueDate", row["date"])
    snapshot["cash_movements"].append({"id": 110, "type": "TRANSACTION", "productId": 20,
        "description": "Vente 2 TEST", "change": 20, "currency": "USD",
        "date": fixture["transactions"][0]["date"], "valueDate": fixture["transactions"][0]["date"]})
    snapshot["update"]["portfolio"]["value"][-1]["value"][-1]["value"] = 8
    snapshot["to_date"] = "2026-01-04"
    snapshot["fetch_started_at"] = "2026-01-04T12:00:00Z"
    snapshot["fetched_at"] = "2026-01-04T12:00:01Z"
    snapshot["history_completeness_verified"] = False
    snapshot["account_report_csv"] = cash_statement(snapshot)
    destination = deepcopy(loaded["captures"]["destination"])
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    config = {"source_account": "123", "target_account": "target-a", "dry_run": True,
        "sync_mode": "prospective", "cutover_manifest": str(manifest_path),
        "cutover_sha256": digest, "state_dir": str(state), "ghost_host": "http://localhost:3333"}
    return config, snapshot, destination


def sync_account(account, importer=None, writer=None):
    config, snapshot, destination = account
    return adapter.synchronize_account(config, snapshot, destination["account"],
        destination["activities"], MAPPING, QUOTES,
        importer or (lambda unused: pytest.fail("Unexpected POST")),
        writer or (lambda *unused: pytest.fail("Unexpected PUT")),
        now=datetime.fromisoformat(snapshot["fetched_at"]))


def test_full_prospective_dry_run_has_exact_plan_without_history_claim(prospective_account):
    config, snapshot, destination = prospective_account
    before = deepcopy(destination)
    result = sync_account(prospective_account)
    assert len(result["proposed"]) == 3
    assert {row["type"] for row in result["proposed"]} == {"SELL", "DIVIDEND", "FEE"}
    assert result["accepted"] == [] and result["prospective_verified"] is True
    assert result["history_verified"] is False and result["basis_status"] == "unverified"
    assert destination == before


def test_stale_destination_cash_does_not_block_verified_dry_run(prospective_account):
    config, snapshot, destination = prospective_account
    path = Path(config['cutover_manifest'])
    manifest = yaml.safe_load(path.read_bytes())
    capture_path = path.parent / manifest['opening']['destination']['path']
    capture = json.loads(capture_path.read_bytes())
    capture['account']['balance'] = 0
    manifest['opening']['destination']['sha256'] = private_file(capture_path, json.dumps(capture).encode())
    config['cutover_sha256'] = private_file(path, yaml.safe_dump(manifest).encode())
    destination['account']['balance'] = 0
    before = deepcopy(destination)
    result = sync_account(prospective_account)
    assert result['prospective_verified'] is True and result['cash'] == 12.3
    assert result['accepted'] == [] and destination == before
    # A stale destination never excuses inconsistent broker cash evidence.
    snapshot['update']['cashFunds']['value'][0]['value'][-1]['value'] = 999
    with pytest.raises(RuntimeError):
        sync_account(prospective_account)


def test_first_and_repeat_preserve_legacy_and_use_opening_inventory(prospective_account):
    config, snapshot, destination = prospective_account
    config["dry_run"] = False
    body = destination["activities"]
    opening = deepcopy(body["activities"][0])
    imports, balances = [], []
    def post(batch):
        imports.extend(deepcopy(batch))
        for activity in batch:
            row = deepcopy(activity)
            row["id"] = "created-" + str(len(body["activities"]))
            row["assetProfile"] = {"symbol": row.pop("symbol"), "dataSource": row.pop("dataSource")}
            body["activities"].append(row)
        body["count"] = len(body["activities"])
        return deepcopy(batch), True
    first = sync_account(prospective_account, post, lambda *args: balances.append(args) or True)
    assert len(first["accepted"]) == 3 and first["history_verified"] is False
    assert body["activities"][0] == opening
    assert adapter.existing_activity_context(body, destination["account"])[1] == {("target-a", "TEST"): 8}
    second = sync_account(prospective_account, post, lambda *args: balances.append(args) or True)
    assert second["proposed"] == [] and len(imports) == 3
    assert body["activities"][0] == opening


@pytest.mark.parametrize("mutation", ["coverage", "missing_statement", "statement_mismatch",
    "late_event", "changed_legacy", "holdings", "future", "value_date", "manual_overlap",
    "unknown", "missing_execution", "missing_execution_cash", "changed_identity"])
def test_prospective_preflight_refuses_all_writes(prospective_account, mutation):
    config, snapshot, destination = prospective_account
    config["dry_run"] = False
    if mutation == "coverage":
        snapshot["from_date"] = "2026-01-01"
    elif mutation == "missing_statement":
        snapshot.pop("account_report_csv")
    elif mutation == "statement_mismatch":
        snapshot["account_report_csv"] = snapshot["account_report_csv"].replace("-2,5", "-2,51")
    elif mutation == "late_event":
        row = deepcopy(snapshot["cash_movements"][0])
        row.update(id=999, date=CUTOVER, valueDate=CUTOVER)
        snapshot["cash_movements"].append(row)
        snapshot["account_report_csv"] = cash_statement(snapshot)
    elif mutation == "changed_legacy":
        destination["activities"]["activities"][0]["unitPrice"] = 2
    elif mutation == "holdings":
        snapshot["update"]["portfolio"]["value"][-1]["value"][-1]["value"] = 9
    elif mutation == "future":
        snapshot["cash_movements"][0]["date"] = "2026-01-05T00:00:00Z"
        snapshot["account_report_csv"] = cash_statement(snapshot)
    elif mutation == "value_date":
        snapshot["cash_movements"][0]["valueDate"] = CUTOVER
        snapshot["account_report_csv"] = cash_statement(snapshot)
    elif mutation in ("manual_overlap", "changed_identity"):
        row = deepcopy(destination["activities"]["activities"][0])
        row.update(id="other", date="2026-01-02T09:00:00Z", type="SELL", quantity=2)
        if mutation == "changed_identity":
            row["comment"] = "DEGIRO#123:TRADE:10"
        destination["activities"]["activities"].append(row)
        destination["activities"]["count"] += 1
    elif mutation == "unknown":
        snapshot["cash_movements"][0]["description"] = "Unknown financial event"
        snapshot["account_report_csv"] = cash_statement(snapshot)
    elif mutation == "missing_execution":
        snapshot["transactions"].clear()
    else:
        snapshot["cash_movements"] = [row for row in snapshot["cash_movements"] if row["type"] != "TRANSACTION"]
        snapshot["account_report_csv"] = cash_statement(snapshot)
    calls = []
    with pytest.raises(RuntimeError):
        sync_account(prospective_account, lambda rows: calls.append("post"), lambda *args: calls.append("put"))
    assert calls == []


def test_prospective_uncertain_import_fences_new_sync(prospective_account):
    config, snapshot, destination = prospective_account
    config["dry_run"] = False
    attempts = []
    def uncertain(batch):
        attempts.append(batch)
        raise RuntimeError("Lost response")
    with pytest.raises(RuntimeError, match="uncertain"):
        sync_account(prospective_account, uncertain)
    assert len(attempts) == 1
    config["dry_run"] = True
    with pytest.raises(RuntimeError, match="durable write intent"):
        sync_account(prospective_account)


def test_actual_dry_run_command_exercises_config_and_orchestration(prospective_account, tmp_path, monkeypatch, caplog):
    config, snapshot, destination = prospective_account
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(yaml.safe_dump({"US0378331005": {"symbol": "TEST", "currency": "USD"}}))
    for key, value in {"GHOST_HOST": config["ghost_host"], "GHOST_TOKEN": "synthetic-token",
            "GHOST_ACCOUNT_ID": "target-a", "DEGIRO_ACCOUNT_ID": "123", "DRY_RUN": "1",
            "SYNC_MODE": "prospective", "CUTOVER_MANIFEST": config["cutover_manifest"],
            "CUTOVER_SHA256": config["cutover_sha256"], "STATE_DIR": config["state_dir"],
            "MAPPING_FILE": str(mapping_path)}.items():
        monkeypatch.setenv(key, value)
    # Real run_sync/load_sync_config and real synchronize_locked, with only acquisition replaced.
    def acquired(cfg, mapping, quotes, from_date, to_date, window_days, journal=None):
        return adapter.synchronize_locked(cfg, snapshot, destination["account"], destination["activities"],
            mapping, quotes, lambda rows: pytest.fail("POST"), lambda *args: pytest.fail("PUT"),
            now=datetime.fromisoformat(snapshot["fetched_at"]), journal=journal)
    monkeypatch.setattr(adapter, "run_sync_locked", acquired)
    with caplog.at_level("INFO"):
        assert adapter.main(["--sync", "--from-date", "2025-12-31", "--to-date", "2026-01-04"]) == 0
    assert "historical completeness and basis remain unverified" in caplog.text
    snapshot["from_date"] = "2026-01-01"
    assert adapter.main(["--sync", "--from-date", "2025-12-31", "--to-date", "2026-01-04"]) == 1


def test_dry_run_command_keeps_acquisition_scope_and_read_only_transports(prospective_account, tmp_path, monkeypatch, caplog):
    config, snapshot, destination = prospective_account
    now = datetime.now(timezone.utc)
    snapshot["fetch_started_at"] = (now - timedelta(seconds=1)).isoformat()
    snapshot["fetched_at"] = now.isoformat()
    snapshot["to_date"] = (now + timedelta(days=1)).date().isoformat()
    mapping_path = tmp_path / "runtime-mapping.yaml"
    mapping_path.write_text(yaml.safe_dump({"US0378331005": {"symbol": "TEST", "currency": "USD"}}))
    for key, value in {"GHOST_HOST": config["ghost_host"], "GHOST_TOKEN": "synthetic-token",
            "GHOST_ACCOUNT_ID": "target-a", "DEGIRO_ACCOUNT_ID": "123", "DRY_RUN": "1",
            "SYNC_MODE": "prospective", "CUTOVER_MANIFEST": config["cutover_manifest"],
            "CUTOVER_SHA256": config["cutover_sha256"], "STATE_DIR": config["state_dir"],
            "MAPPING_FILE": str(mapping_path)}.items():
        monkeypatch.setenv(key, value)
    acquired, requests = [], []
    def read(start, end, days, **kwargs):
        acquired.append((start, end, days, kwargs))
        return deepcopy(snapshot)
    def get(url):
        requests.append(url)
        body = destination["activities"] if url.endswith("/activities") else destination["account"]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: deepcopy(body))
    @contextmanager
    def transport(cfg, target):
        yield SimpleNamespace(get=get)
    monkeypatch.setattr(adapter, "read_degiro", read)
    monkeypatch.setattr(adapter, "ghost_transport", transport)
    monkeypatch.setattr(adapter.core, "ghost_import_activities", lambda *args: pytest.fail("POST"))
    monkeypatch.setattr(adapter.core, "ghost_update_cash_balance", lambda *args: pytest.fail("PUT"))
    # A narrow requested lookback cannot replace the manifest's full replay interval.
    with caplog.at_level('INFO'):
        assert adapter.main(["--sync", "--from-date", now.date().isoformat()]) == 0
    assert 'Proposed Ghostfolio cash balance: EUR 12.30; DRY_RUN, no update sent' in caplog.text
    assert acquired[0][0].isoformat() == "2025-12-31"
    assert acquired[0][3] == {"report_locale": ("fr", "fr"), "holdings": True}
    assert len(requests) == 2 and all(url.startswith(config["ghost_host"]) for url in requests)
    monkeypatch.setenv("CUTOVER_SHA256", "0" * 64)
    assert adapter.main(["--sync"]) == 1
    assert len(acquired) == 1 and len(requests) == 2


def test_prepare_command_publishes_only_after_validating_and_refuses_overwrite(evidence, tmp_path, capsys):
    from scripts import prepare_cutover
    loaded, manifest_path, unused_digest = evidence
    mapping_path = tmp_path / "private-mapping.yaml"
    mapping_digest = private_file(mapping_path, yaml.safe_dump({
        "US0378331005": {"symbol": "TEST", "currency": "USD"}}).encode())
    output = tmp_path / "prepared.yaml"
    args = ["--source-account", "123", "--target-account", "target-a", "--output", str(output),
        "--mapping", str(mapping_path), "--mapping-sha256", mapping_digest]
    before = {}
    for name, binding in loaded["manifest"]["opening"].items():
        path = manifest_path.parent / binding["path"]
        before[path] = path.read_bytes()
        args += ["--" + name, str(path), "--" + name + "-sha256", binding["sha256"]]
    assert prepare_cutover.main(args) == 0
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert "CUTOVER_SHA256=" + digest in capsys.readouterr().out
    assert adapter.prospective_opening_context(adapter.load_prospective_evidence(output, digest),
        {"source_account": "123", "target_account": "target-a"}, MAPPING, QUOTES)["quantities"] == {
            ("target-a", "TEST"): 10}
    assert output.stat().st_mode & 0o777 == 0o600
    unchanged = output.read_bytes()
    assert prepare_cutover.main(args) == 1
    assert output.read_bytes() == unchanged
    assert all(path.read_bytes() == content for path, content in before.items())


def test_prepare_rejects_input_output_alias_and_missing_evidence(evidence, tmp_path):
    from scripts import prepare_cutover
    loaded, manifest_path, unused_digest = evidence
    mapping = tmp_path / "map.yaml"
    digest = private_file(mapping, yaml.safe_dump({
        "US0378331005": {"symbol": "TEST", "currency": "USD"}}).encode())
    args = ["--source-account", "123", "--target-account", "target-a", "--mapping", str(mapping),
        "--mapping-sha256", digest, "--output", str(mapping)]
    for name, binding in loaded["manifest"]["opening"].items():
        args += ["--" + name, str(manifest_path.parent / binding["path"]),
            "--" + name + "-sha256", binding["sha256"]]
    original = mapping.read_bytes()
    assert prepare_cutover.main(args) == 1
    assert mapping.read_bytes() == original
    broker_path = manifest_path.parent / loaded["manifest"]["opening"]["broker"]["path"]
    broker_path.chmod(0o644)
    fresh_output = tmp_path / "refused.yaml"
    args[args.index("--output") + 1] = str(fresh_output)
    assert prepare_cutover.main(args) == 1
    assert not fresh_output.exists()
    assert mapping.read_bytes() == original


def test_submillisecond_source_time_refused_before_native_dispatch(prospective_account):
    config, snapshot, destination = prospective_account
    config['dry_run'] = False
    for row in snapshot['transactions'] + snapshot['cash_movements']:
        if row['date'] == '2026-01-02T10:00:00+01:00':
            row['date'] = '2026-01-02T10:00:00.000001+01:00'
    snapshot['account_report_csv'] = cash_statement(snapshot)
    with pytest.raises(RuntimeError, match='precision'):
        sync_account(prospective_account)


def test_read_only_capture_publishes_private_candidates_without_financial_writes(
        evidence, tmp_path, monkeypatch):
    from scripts import prepare_cutover
    loaded, unused_path, unused_digest = evidence
    config = {'dry_run': True, 'ghost_host': 'http://localhost:3333', 'source_account': '123',
        'target_account': 'target-a'}
    monkeypatch.setattr(adapter, 'load_sync_config', lambda: (config, MAPPING, QUOTES))
    calls = []
    @contextmanager
    def transport(cfg, target):
        def get(url):
            calls.append(url)
            value = loaded['captures']['destination'][
                'activities' if url.endswith('/activities') else 'account']
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: deepcopy(value))
        yield SimpleNamespace(get=get)
    def read(start, end, **kwargs):
        assert kwargs['holdings'] and kwargs['report_locale'] == ('fr', 'fr')
        result = deepcopy(loaded['captures']['broker'])
        result['fetch_started_at'] = datetime.now(timezone.utc).isoformat()
        result['opening_destination'] = kwargs['cutover_target_reader']()
        result['fetched_at'] = datetime.now(timezone.utc).isoformat()
        result['from_date'], result['to_date'] = start.isoformat(), end.isoformat()
        return result
    monkeypatch.setattr(adapter, 'ghost_transport', transport)
    monkeypatch.setattr(adapter, 'read_degiro', read)
    monkeypatch.setattr(adapter.core, 'ghost_import_activities', lambda *args: pytest.fail('POST'))
    monkeypatch.setattr(adapter.core, 'ghost_update_cash_balance', lambda *args: pytest.fail('PUT'))
    output = tmp_path / 'capture'
    prepare_cutover.capture(output, config)
    assert len(calls) == 2
    for name in ('broker', 'destination'):
        path = output / (name + '.json')
        assert path.is_file() and path.stat().st_mode & 0o777 == 0o600
    before = (output / 'broker.json').read_bytes()
    with pytest.raises(FileExistsError):
        prepare_cutover.capture(output, config)
    assert len(calls) == 2 and (output / 'broker.json').read_bytes() == before
    mapping_path = tmp_path / "mapping.yaml"
    private_file(mapping_path, yaml.safe_dump({
        "US0378331005": {"symbol": "TEST", "currency": "USD"}}).encode())
    monkeypatch.setenv("MAPPING_FILE", str(mapping_path))
    combined = tmp_path / "combined"
    assert prepare_cutover.main(["--capture", "--output-directory", str(combined)]) == 0
    manifest = combined / "manifest.yaml"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert opening_context(adapter.load_prospective_evidence(manifest, digest))["cutover"]
    assert len(calls) == 4
    config['dry_run'] = False
    assert prepare_cutover.main(["--capture", "--output-directory",
        str(tmp_path / "live-refusal")]) == 1
    with pytest.raises(RuntimeError):
        prepare_cutover.capture(tmp_path / 'live-refusal', config)
    assert not (tmp_path / 'live-refusal').exists()


@pytest.mark.parametrize('failure, expected', [
    ('DEGIRO login failed: captcha_required', 'DEGIRO login failed: captcha_required'),
    ('DEGIRO read failed at cutover_destination; no financial writes attempted',
     'DEGIRO read failed at cutover_destination; no financial writes attempted'),
    ('private bearer=secret and account payload', None),
    ('DEGIRO login failed: captcha_required private bearer=secret', None),
])
def test_capture_failure_reports_safe_stage_without_private_details(monkeypatch, capsys, tmp_path,
                                                                   failure, expected):
    from scripts import prepare_cutover
    monkeypatch.setattr(adapter, 'load_sync_config', lambda: ({'dry_run': True}, {}, {}))
    def refuse(*args):
        raise RuntimeError(failure)
    monkeypatch.setattr(prepare_cutover, 'capture', refuse)
    assert prepare_cutover.main(['--capture', '--output-directory', str(tmp_path / 'capture')]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'Cutover preparation refused; retained evidence is not approval' in output.err
    assert 'secret' not in output.err and 'payload' not in output.err
    if expected:
        assert expected in output.err
    else:
        assert output.err == 'Cutover preparation refused; retained evidence is not approval\n'


def test_distinct_same_minute_source_rows_preserve_multiset(prospective_account):
    config, snapshot, destination = prospective_account
    extra = deepcopy(snapshot['cash_movements'][3])
    extra['id'] = 999
    snapshot['cash_movements'].append(extra)
    snapshot['account_report_csv'] = cash_statement(snapshot)
    result = sync_account(prospective_account)
    assert len(result['proposed']) == 4
    assert {row['comment'] for row in result['proposed'] if row['type'] == 'FEE'} == {
        'DEGIRO#123:FEE:104', 'DEGIRO#123:FEE:999'}
    snapshot['account_report_csv'] = cash_statement({**snapshot,
        'cash_movements': snapshot['cash_movements'][:-1]})
    with pytest.raises(RuntimeError, match='coverage'):
        sync_account(prospective_account)


def test_uncertain_cash_remains_fenced_with_no_coverage_checkpoint(prospective_account):
    config, snapshot, destination = prospective_account
    config['dry_run'] = False
    def post(batch):
        for activity in batch:
            row = deepcopy(activity)
            row['id'] = 'created-' + str(len(destination['activities']['activities']))
            row['assetProfile'] = {'symbol': row.pop('symbol'), 'dataSource': row.pop('dataSource')}
            destination['activities']['activities'].append(row)
        destination['activities']['count'] = len(destination['activities']['activities'])
        return batch, True
    with pytest.raises(RuntimeError, match='Uncertain cash'):
        sync_account(prospective_account, post, lambda *args: False)
    with adapter.account_journal(config) as journal:
        assert journal['document']['pending']['kind'] == 'cash'
        assert set(journal['document']) == {'version', 'owner', 'pending', 'resolved'}
    config['dry_run'] = True
    with pytest.raises(RuntimeError, match='durable write intent'):
        sync_account(prospective_account)


def test_overlap_multiplicity_and_timezone_cutover_are_exact(prospective_account):
    config, snapshot, destination = prospective_account
    # Equal offsets describe one instant, but no approximate date matching is used.
    snapshot['transactions'][0]['date'] = '2026-01-02T09:00:00Z'
    result = sync_account(prospective_account)
    assert len(result['proposed']) == 3
    snapshot['transactions'].append(deepcopy(snapshot['transactions'][0]))
    assert len(sync_account(prospective_account)['proposed']) == 3
    snapshot['transactions'][-1]['price'] = 11
    with pytest.raises(RuntimeError):
        sync_account(prospective_account)


def test_missing_protected_legacy_and_new_pre_cutover_rows_refuse(prospective_account):
    config, snapshot, destination = prospective_account
    config['dry_run'] = False
    row = deepcopy(destination['activities']['activities'][0])
    destination['activities'] = {'count': 0, 'activities': []}
    with pytest.raises(RuntimeError, match='Protected'):
        sync_account(prospective_account)
    destination['activities'] = {'count': 2, 'activities': [row, {**row, 'id': 'unexpected'}]}
    with pytest.raises(RuntimeError, match='Protected'):
        sync_account(prospective_account)


@pytest.mark.parametrize('stamp', ['2026-01-02T10:00+01:00', '2026-01-02T10:00:00',
    '2026-01-02', '2026-01-02 10:00:00+01:00'])
def test_ambiguous_timestamp_precision_refused(prospective_account, stamp):
    config, snapshot, destination = prospective_account
    config['dry_run'] = False
    snapshot['cash_movements'][3]['date'] = stamp
    parsed = datetime.fromisoformat(stamp)
    if parsed.utcoffset() is not None:
        snapshot["account_report_csv"] = cash_statement(snapshot)
        with pytest.raises(RuntimeError, match="precision"):
            sync_account(prospective_account)
    else:
        with pytest.raises(RuntimeError, match="offset"):
            sync_account(prospective_account)


def test_minute_only_cutover_and_capture_clocks_refused(evidence):
    loaded, unused_path, unused_digest = evidence
    loaded['manifest']['cutover'] = '2025-12-31T12:00+00:00'
    loaded['captures']['broker']['fetched_at'] = '2025-12-31T12:00+00:00'
    with pytest.raises(RuntimeError, match='precision'):
        opening_context(loaded)


@pytest.mark.parametrize("mismatch", [False, True])
def test_closed_holding_needs_no_metadata_but_requires_identity(evidence, mismatch):
    loaded, unused_path, unused_digest = evidence
    snapshot = deepcopy(loaded["captures"]["broker"])
    snapshot["update"]["portfolio"]["value"].append({"id": "99", "name": "positionrow",
        "value": [{"name": "id", "value": "98" if mismatch else "99"},
                  {"name": "size", "value": 0}]})
    if mismatch:
        with pytest.raises(RuntimeError, match="identity"):
            adapter.broker_stock_holdings(snapshot, {"id": "target-a"}, MAPPING, QUOTES)
    else:
        assert adapter.broker_stock_holdings(snapshot, {"id": "target-a"}, MAPPING, QUOTES) == {
            ("target-a", "TEST"): 10}


@pytest.mark.parametrize('identity, inner, position, size, accepted', [
    ('USD', 'USD', 'CASH', 0, True),
    ('USD', 'EUR', 'CASH', 0, False),
    ('USD', 'USD', 'PRODUCT', 0, False),
    ('unknown', 'unknown', 'CASH', 0, False),
    ('USD', 'USD', 'CASH', 1, False),
    ('USD', 'USD', 'CASH', -1, False),
])
def test_only_identified_empty_currency_cash_placeholders_are_excluded_from_holdings(
        evidence, identity, inner, position, size, accepted):
    loaded, unused_path, unused_digest = evidence
    snapshot = deepcopy(loaded['captures']['broker'])
    snapshot['update']['portfolio']['value'].append({'id': identity, 'name': 'positionrow',
        'value': [{'name': 'id', 'value': inner}, {'name': 'size', 'value': size},
                  {'name': 'positionType', 'value': position}]})
    if accepted:
        assert adapter.broker_stock_holdings(snapshot, {'id': 'target-a'}, MAPPING, QUOTES) == {
            ('target-a', 'TEST'): 10}
    else:
        with pytest.raises(RuntimeError):
            adapter.broker_stock_holdings(snapshot, {'id': 'target-a'}, MAPPING, QUOTES)


def test_minute_only_opening_source_event_refused(evidence):
    loaded, unused_path, unused_digest = evidence
    fixture = yaml.safe_load((Path(__file__).parent / "fixtures/degiro_contract.yaml").read_text())
    row = deepcopy(fixture["cash_movements"]["exchange_connection_fee"])
    row["valueDate"] = "2025-12-31T11:59:00+00:00"
    row["date"] = "2025-12-31T11:59+00:00"
    loaded["captures"]["broker"]["cash_movements"] = [row]
    with pytest.raises(RuntimeError, match="precision"):
        opening_context(loaded)
