"""Approved bounded sync and restart, synthetic account state only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter
from test_prospective import evidence, prospective_account, sync_account, cash_statement
from test_degiro_sync import activity_row


@pytest.fixture
def rolling(prospective_account):
    config, snapshot, destination = prospective_account
    config["sync_mode"] = "rolling"
    config.pop("cutover_manifest")
    config.pop("cutover_sha256")
    snapshot["from_date"] = "2025-10-07"
    return prospective_account


def state(config):
    paths = list(Path(config["state_dir"]).glob("*.yaml"))
    return yaml.safe_load(paths[0].read_bytes()) if paths else None


def test_first_dry_run_proposes_pre_service_events_and_preserves_state(rolling):
    config, snapshot, destination = rolling
    before = deepcopy(destination)
    result = sync_account(rolling)
    assert len(result["proposed"]) == 3
    assert result["rolling_verified"] and not result["history_verified"]
    assert not result["prospective_verified"] and result["accepted"] == []
    assert destination == before and state(config) is None


def test_first_live_repeat_and_success_coverage(rolling):
    config, snapshot, destination = rolling
    config["dry_run"] = False
    def importer(batch):
        for a in batch:
            destination["activities"]["activities"].append(activity_row(a, a["comment"]))
        destination["activities"]["count"] = len(destination["activities"]["activities"])
        return deepcopy(batch), True
    result = sync_account(rolling, importer, lambda *args: True)
    assert len(result["accepted"]) == 3
    assert state(config)["coverage"] == {"from_date": snapshot["from_date"], "through": snapshot["fetched_at"]}
    config["dry_run"] = True
    before = deepcopy(state(config))
    assert sync_account(rolling)["proposed"] == []
    assert state(config) == before


@pytest.mark.parametrize("change", ["gap", "future", "holdings", "conflict", "statement", "missing_execution"])
def test_bad_evidence_refuses_before_writes(rolling, change):
    config, snapshot, destination = rolling
    config["dry_run"] = False
    if change == "gap":
        with adapter.account_journal(config) as journal:
            journal["document"]["coverage"] = {"from_date": "2025-01-01", "through": "2025-10-06T12:00:00Z"}
            adapter.write_journal(journal)
    elif change == "future":
        snapshot["transactions"][0]["date"] = "2026-01-05T00:00:00Z"
    elif change == "holdings":
        snapshot["update"]["portfolio"]["value"][-1]["value"][-1]["value"] = 99
    elif change == "conflict":
        activities = adapter.normalize_trades(snapshot, "target-a", {"US0378331005": "TEST"}, {"TEST": "USD"})
        row = activity_row(activities[0], "changed")
        row["fee"] += 1
        destination["activities"]["activities"].append(row)
        destination["activities"]["count"] += 1
    elif change == "statement":
        snapshot["account_report_csv"] = "broken"
    else:
        snapshot["transactions"] = []
    with pytest.raises(RuntimeError):
        sync_account(rolling)
    assert not state(config) or "coverage" not in state(config) or change == "gap"


def test_explicit_catchup_covers_gap(rolling):
    config, snapshot, destination = rolling
    with adapter.account_journal(config) as journal:
        journal["document"]["coverage"] = {"from_date": "2025-01-01", "through": "2025-10-06T12:00:00Z"}
        adapter.write_journal(journal)
    snapshot["from_date"] = "2025-10-06"
    assert len(sync_account(rolling)["proposed"]) == 3
    assert state(config)["coverage"]["through"] == "2025-10-06T12:00:00Z"


@pytest.mark.parametrize("readback", ["complete", "absent", "partial", "changed", "duplicate"])
def test_restart_only_complete_exact_readback_can_continue(rolling, readback):
    config, snapshot, destination = rolling
    config["dry_run"] = False
    def lost(batch):
        rows = [activity_row(a, a["comment"]) for a in batch]
        if readback == "absent":
            rows = []
        elif readback == "partial":
            rows = rows[:-1]
        elif readback == "changed":
            rows[0]["unitPrice"] += 1
        elif readback == "duplicate":
            rows.append({**rows[0], "id": "duplicate"})
        destination["activities"]["activities"].extend(rows)
        destination["activities"]["count"] = len(destination["activities"]["activities"])
        raise TimeoutError("lost confirmation")
    with pytest.raises(RuntimeError, match="cash blocked"):
        sync_account(rolling, lost)
    config.pop("_uncertain_import_accounts", None)
    original = deepcopy(state(config))
    config["dry_run"] = True
    if readback == "complete":
        assert len(sync_account(rolling)["proposed"]) == 1  # remaining SELL
        assert state(config) == original
        config["dry_run"] = False
        def remainder(batch):
            assert [a["type"] for a in batch] == ["SELL"]
            return deepcopy(batch), True
        assert len(sync_account(rolling, remainder, lambda *a: True)["accepted"]) == 1
        assert state(config)["pending"] is None and "coverage" in state(config)
    else:
        with pytest.raises(RuntimeError):
            sync_account(rolling)
        assert state(config) == original


def test_cash_uncertainty_is_not_automatically_resolved(rolling):
    config, snapshot, destination = rolling
    with adapter.account_journal(config) as journal:
        adapter.begin_intent(journal, "cash", {"account": "target-a", "balance": 12.3})
    before = deepcopy(state(config))
    with pytest.raises(RuntimeError, match="durable write intent"):
        sync_account(rolling)
    assert state(config) == before


@pytest.mark.parametrize("kind,gap,qty,expected", [
    ("BUY", 2, "2", True), ("BUY", 3, "2", False),
    ("BUY", 1, "2.0009", True), ("BUY", 1, "2.001", "refuse"),
    ("SELL", -2, "2", True), ("DIVIDEND", 3, "99", True),
    ("DIVIDEND", 4, "2", False)])
def test_ibkr_manual_matching_boundaries(kind, gap, qty, expected):
    activity = {"accountId": "target-a", "type": kind, "symbol": "TEST", "quantity": 2,
                "date": "2026-01-01T00:00:00Z"}
    row = {**activity, "quantity": qty,
           "date": (datetime(2026, 1, 1) + timedelta(days=gap)).isoformat() + "Z"}
    entries = [row]
    if expected == "refuse":
        with pytest.raises(RuntimeError, match="manual trade"):
            adapter.match_manual_activity(activity, entries)
    else:
        assert adapter.match_manual_activity(activity, entries) is expected
        if expected and kind != "DIVIDEND":
            assert entries == []


def test_matching_manual_sell_prevents_duplicate_and_preserves_holdings(rolling):
    config, snapshot, destination = rolling
    activity = adapter.normalize_trades(snapshot, "target-a", {"US0378331005": "TEST"}, {"TEST": "USD"})[0]
    activity["comment"] = None
    row = activity_row(activity, "manual-sell")
    row["date"] = "2026-01-03T00:00:00Z"
    destination["activities"]["activities"].append(row)
    destination["activities"]["count"] += 1
    assert {a["type"] for a in sync_account(rolling)["proposed"]} == {"DIVIDEND", "FEE"}


def test_actual_command_uses_rolling_today_and_private_read_only_plan(rolling, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from contextlib import contextmanager
    from test_degiro_sync import response
    config, snapshot, destination = rolling
    today = datetime.now(ZoneInfo("Europe/Zurich")).date()
    shift = today - datetime(2026, 1, 4).date()
    for collection in ('transactions', 'cash_movements'):
        for row in snapshot[collection]:
            for key in ('date', 'valueDate'):
                if key in row:
                    row[key] = (datetime.fromisoformat(row[key]) + shift).isoformat()
    now = datetime.now(timezone.utc)
    snapshot['fetch_started_at'] = (now - timedelta(seconds=1)).isoformat()
    snapshot['fetched_at'] = now.isoformat()
    snapshot['from_date'] = (today - timedelta(days=89)).isoformat()
    snapshot['to_date'] = today.isoformat()
    snapshot['account_report_csv'] = cash_statement(snapshot)
    monkeypatch.setenv('SYNC_MODE', 'rolling')
    monkeypatch.setenv('DRY_RUN', '1')
    monkeypatch.setenv('GHOST_HOST', config['ghost_host'])
    monkeypatch.setenv('GHOST_TOKEN', 'synthetic-token')
    monkeypatch.setenv('GHOST_ACCOUNT_ID', config['target_account'])
    monkeypatch.setenv('DEGIRO_ACCOUNT_ID', config['source_account'])
    monkeypatch.setenv('STATE_DIR', config['state_dir'])
    mapping = tmp_path / 'mapping.yaml'
    mapping.write_text(yaml.safe_dump({'US0378331005': {'symbol': 'TEST', 'currency': 'USD'}}))
    monkeypatch.setenv('MAPPING_FILE', str(mapping))
    queried = []
    def acquire(start, end, window_days, **kwargs):
        queried.append((start.isoformat(), end.isoformat(), kwargs))
        return deepcopy(snapshot)
    monkeypatch.setattr(adapter, 'read_degiro', acquire)
    reads = []
    def get(url):
        reads.append(url)
        return response(destination['account'] if '/account/' in url else destination['activities'])
    @contextmanager
    def transport(cfg, target):
        assert cfg['dry_run'] is True
        yield SimpleNamespace(get=get)
    monkeypatch.setattr(adapter, 'ghost_transport', transport)
    monkeypatch.setattr(adapter.core, 'ghost_import_activities', lambda *a: pytest.fail('POST'))
    monkeypatch.setattr(adapter.core, 'ghost_update_cash_balance', lambda *a: pytest.fail('PUT'))
    assert adapter.main(['--sync']) == 0
    assert queried == [(snapshot['from_date'], snapshot['to_date'], {'report_locale': ('fr', 'fr'), 'holdings': True})]
    assert len(reads) == 2 and state(config) is None
    assert adapter.main(['--sync', '--from-date', today.isoformat()]) == 1
    assert len(queried) == 1
    monkeypatch.setenv('LOOKBACK_DAYS', '30')
    assert adapter.main(['--sync']) == 1
    assert len(queried) == 1


def test_manual_match_never_hides_changed_canonical_identity(rolling):
    config, snapshot, destination = rolling
    a = adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'USD'})[0]
    manual = activity_row({**a, 'comment': None}, 'manual')
    canonical = activity_row({**a, 'fee': a['fee'] + 1}, 'canonical')
    destination['activities']['activities'].extend([manual, canonical])
    destination['activities']['count'] += 2
    with pytest.raises(RuntimeError, match='changed financial evidence'):
        sync_account(rolling)


def test_repeated_source_identity_does_not_consume_manual_entry_twice():
    a = {'accountId': 'target-a', 'comment': 'DEGIRO#123:TRADE:10', 'currency': 'USD',
         'dataSource': 'YAHOO', 'date': '2026-01-01T00:00:00Z', 'fee': 0,
         'quantity': 2, 'symbol': 'TEST', 'type': 'BUY', 'unitPrice': 10}
    manual = {**a, 'comment': None}
    assert adapter.pending_activities([a, deepcopy(a)], [manual], {'id': 'target-a'}, '123',
                                      manual_matching=True) == []
