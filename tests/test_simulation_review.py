"""Reviewable simulations use disposable files and synthetic financial evidence."""
from copy import deepcopy
from collections import Counter
import json
import logging

import pytest

import degiro_to_ghostfolio as adapter


@pytest.fixture
def review(monkeypatch, tmp_path, caplog):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("CRON", "15 6 * * *")
    caplog.set_level(logging.INFO, logger=adapter.__name__)
    result = {"dry_run": True, "proposed": [{"type": "DIVIDEND", "symbol": "TEST",
        "date": "2026-10-09T00:00:00Z", "quantity": 1, "unitPrice": 12.5,
        "currency": "USD", "fee": 1.8, "comment": "DEGIRO#123:DIVIDEND:42",
        "accountId": "private-target", "dataSource": "YAHOO"}],
        "cash": 42.5, "cash_before": 30, "accepted": [], "history_verified": False,
        "rolling_verified": True, "candidates": 5,
        "exclusions": {"already_imported": 2, "manual_match": 1, "duplicate_candidate": 1}}
    monkeypatch.setattr(adapter, "run_sync", lambda *a: deepcopy(result))
    return result


def test_scheduled_dry_run_logs_decision_details_without_creating_reports(review, tmp_path, caplog):
    for _ in range(2):
        assert adapter.main(["--sync"]) == 0
    assert "2026-10-09T00:00:00Z" in caplog.text
    assert "DIVIDEND" in caplog.text and "TEST" in caplog.text
    assert "qty=1 price=12.5 USD fee=1.8" in caplog.text
    assert "EUR 30.00 -> 42.50" in caplog.text
    assert "already_imported=2 manual_match=1 duplicate_candidate=1" in caplog.text
    assert "DEGIRO#123" not in caplog.text and "private-target" not in caplog.text
    assert not list(tmp_path.iterdir())


def test_optional_plan_contains_review_context_and_preserves_previous_file(review, tmp_path):
    destination = tmp_path / "review.json"
    assert adapter.main(["--sync", "--plan-output", str(destination)]) == 0
    original = destination.read_bytes()
    data = json.loads(original)
    assert data["activities"] == review["proposed"]
    assert data["cash_before"] == 30 and data["cash"] == 42.5
    assert data["exclusions"] == review["exclusions"]
    assert data["period"]["to_date"] and data["period"]["from_date"]
    assert data["period"]["timezone"] == "Europe/Zurich"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert adapter.main(["--sync", "--plan-output", str(destination)]) == 1
    assert destination.read_bytes() == original


def test_failed_dry_run_saves_no_report(review, tmp_path, monkeypatch):
    def failed(*args):
        raise RuntimeError("PRIVATE RESPONSE SENTINEL")
    monkeypatch.setattr(adapter, "run_sync", failed)
    assert adapter.main(["--sync"]) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_custom_symbol_hides_source_account_and_escapes_log_control_characters(review, monkeypatch, caplog):
    fee = {**review["proposed"][0], "type": "FEE", "symbol": "GF_DEGIRO_123_EXCHANGE_CONNECTION_EUR"}
    symbol = {**review["proposed"][0], "symbol": "TEST\nINJECTED"}
    monkeypatch.setattr(adapter, "run_sync", lambda *a: {**review, "proposed": [fee, symbol]})
    assert adapter.main(["--sync"]) == 0
    assert "GF_DEGIRO_EXCHANGE_CONNECTION_EUR" in caplog.text
    assert "GF_DEGIRO_123" not in caplog.text
    assert "TEST\\nINJECTED" in caplog.text and "TEST\nINJECTED" not in caplog.text


def test_repeated_normalized_candidate_is_counted_once(review):
    activity = review["proposed"][0]
    counts = Counter()
    result = adapter.pending_activities([activity, deepcopy(activity)], [],
        {"id": "private-target"}, "123", exclusions=counts)
    assert result == [activity] and counts == {"duplicate_candidate": 1}


def test_live_run_does_not_publish_private_simulation_or_activity_details(review, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(adapter, "run_sync", lambda *a: {**review, "dry_run": False})
    assert adapter.main(["--sync"]) == 0
    assert not list(tmp_path.rglob("*.json"))
    assert "DIVIDEND" not in caplog.text and "TEST" not in caplog.text
