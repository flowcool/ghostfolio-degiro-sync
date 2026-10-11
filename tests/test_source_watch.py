"""Source revisions generate bounded human review notices, never repinning."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("source_watch", Path("scripts/watch_source_updates.py"))
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


def fake_api(issues=None, latest="b" * 40, fail=None):
    api = SimpleNamespace(issues=list(issues or []), writes=[])
    def listing(path):
        return api.issues if "/issues?" in path else [{"name": "upstream-source"}]
    def request(method, path, payload=None):
        if fail and fail in path:
            raise RuntimeError("Synthetic upstream failure")
        if method == "GET":
            return {"sha": latest} if "/commits/" in path else {"default_branch": "main"}
        api.writes.append(payload)
        issue = {"number": len(api.issues) + 1, "body": payload["body"]}
        api.issues.append(issue)
        return issue
    api.list_all, api.request = listing, request
    return api


def test_real_source_provenance_has_all_consumed_sources():
    assert {pin["repository"] for pin in watch.source_pins()} == {
        "flowcool/ghostfolio-ibkr-sync", "Chavithra/degiro-connector", "dickwolff/Export-To-Ghostfolio"}


def test_notices_compare_exact_revisions_and_closed_notices_remain_acknowledged():
    pins = [{"repository": "owner/source", "commit": "a" * 40}]
    api = fake_api()
    assert watch.monitor(api, "owner/destination", pins) == [1]
    assert "a" * 40 + "..." + "b" * 40 in api.writes[0]["body"]
    assert "does not repin" in api.writes[0]["body"]
    api.issues[0]["state"] = "closed"
    assert watch.monitor(api, "owner/destination", pins) == []
    assert len(api.writes) == 1


def test_pr_marker_does_not_acknowledge_revision_and_watch_caps_ten():
    api = fake_api([{"body": "<!-- upstream-source:owner/source0:" + "b" * 40 + " -->", "pull_request": {}}])
    pins = [{"repository": f"owner/source{i}", "commit": "a" * 40} for i in range(12)]
    assert len(watch.monitor(api, "owner/destination", pins)) == 10


def test_source_failure_never_leaves_partial_notices():
    api = fake_api(fail="source2")
    pins = [{"repository": "owner/source1", "commit": "a" * 40},
            {"repository": "owner/source2", "commit": "a" * 40}]
    with pytest.raises(RuntimeError):
        watch.monitor(api, "owner/destination", pins)
    assert api.writes == []


def test_pins_matching_upstream_never_write():
    api = fake_api(latest="a" * 40)
    assert watch.monitor(api, "owner/destination", [{"repository": "owner/source", "commit": "a" * 40}]) == []
    assert api.writes == []


def test_duplicate_source_pins_create_one_notice():
    pin = {"repository": "owner/source", "commit": "a" * 40}
    api = fake_api()
    assert watch.monitor(api, "owner/destination", [pin, pin]) == [1]


def test_unsafe_source_pin_refused_before_metadata_request():
    api = fake_api()
    api.request = lambda *a: pytest.fail("Unsafe pin reached API")
    with pytest.raises(ValueError):
        watch.monitor(api, "owner/destination", [{"repository": "owner/source?token=secret", "commit": "a" * 40}])
