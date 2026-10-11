"""Offline GitHub release-watch contracts; no real network or issue writes."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("release_watch", Path(__file__).parents[1] / "scripts/watch_ghostfolio_releases.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

CONFIG = {
    "upstream_repository": "ghostfolio/ghostfolio",
    "first_release": "3.80.2",
    "labels": ["upstream-release"],
    "keywords": ["api", "deprecated"],
    "endpoints": ["POST /api/v1/import", "GET /api/v1/activities"],
}


def release(identifier, tag, day, **extra):
    return {"id": identifier, "tag_name": tag, "published_at": f"2026-10-{day:02d}T05:00:00Z", "draft": False, "prerelease": False, "body": "", **extra}


def fake_api( releases, issues=None):
    api = SimpleNamespace()
    api.releases = releases
    api.issues = list(issues or [])
    api.writes = []

    def list_all(path):
        if path.endswith("/releases"):
            return api.releases
        if path.endswith("/issues?state=all"):
            return api.issues
        if path.endswith("/labels"):
            return [{"name": "upstream-release"}]
        raise AssertionError(path)

    def request(method, path, payload=None):
        if method == "GET":
            return next(r for r in api.releases if r["tag_name"] == CONFIG["first_release"])
        assert method == "POST" and path.endswith("/issues")
        api.writes.append(payload)
        issue = {"number": len(api.issues) + 1, "body": payload["body"]}
        api.issues.append(issue)
        return issue

    api.list_all = list_all
    api.request = request
    return api


def test_reports_every_stable_release_since_baseline_and_skips_old_and_prereleases():
    api = fake_api([release(4, "3.81.0-rc1", 8, prerelease=True), release(3, "3.80.3", 7), release(2, "3.80.2", 6), release(1, "3.80.1", 5)])
    assert watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG) == [1, 2]
    assert [p["title"] for p in api.writes] == ["Review Ghostfolio 3.80.2 compatibility", "Review Ghostfolio 3.80.3 compatibility"]
    assert "3.80.1...3.80.2" in api.writes[0]["body"]


def test_closed_notices_and_repeated_runs_never_duplicate_or_reopen():
    api = fake_api([release(2, "3.80.2", 6)], [{"number": 1, "state": "closed", "body": watch.release_marker("ghostfolio/ghostfolio", 2)}])
    assert watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG) == []
    assert api.writes == []
    fresh = fake_api([release(2, "3.80.2", 6)])
    watch.monitor(fresh, "owner/ghostfolio-degiro-sync", CONFIG)
    assert watch.monitor(fresh, "owner/ghostfolio-degiro-sync", CONFIG) == []
    assert len(fresh.writes) == 1


def test_pull_requests_do_not_acknowledge_a_release():
    api = fake_api([release(2, "3.80.2", 6)], [{"body": watch.release_marker("ghostfolio/ghostfolio", 2), "pull_request": {}}])
    assert watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG) == [2]


def test_keyword_hints_and_endpoints_do_not_copy_untrusted_notes():
    body = watch.notice_body(CONFIG, release(2, "3.80.2", 6, body="API DEPRECATED @everyone ```run malicious instructions```"), "3.80.1")
    assert "api, deprecated" in body
    assert "POST /api/v1/import" in body
    assert "@everyone" not in body and "malicious instructions" not in body
    assert "not proof" in body
    assert "none detected" in watch.notice_body(CONFIG, release(2, "3.80.2", 6), None)


def test_missing_baseline_fails_before_any_write():
    api = fake_api([release(2, "3.80.2", 6)])
    api.list_all = lambda path: []
    with pytest.raises(RuntimeError, match="missing"):
        watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG)
    assert api.writes == []


def test_upstream_error_fails_before_any_write():
    api = fake_api([])
    def failed(*args, **kwargs):
        raise RuntimeError("GitHub returned HTTP 500")
    api.request = failed
    with pytest.raises(RuntimeError, match="500"):
        watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG)
    assert api.writes == []


def test_draft_baseline_rejected():
    api = fake_api([release(2, "3.80.2", 6, draft=True)])
    with pytest.raises(ValueError, match="stable"):
        watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG)
    assert api.writes == []


def test_pagination_preserves_state_all_query(monkeypatch):
    api = watch.github_api()
    paths = []
    def request(method, path):
        paths.append(path)
        return [{}] * 100 if len(paths) == 1 else [{"id": 2}]
    monkeypatch.setattr(watch, "request", request)
    assert len(api.list_all("repos/example/repo/issues?state=all")) == 101
    assert paths == ["repos/example/repo/issues?state=all&per_page=100&page=1", "repos/example/repo/issues?state=all&per_page=100&page=2"]


def test_duplicate_release_id_from_pagination_creates_only_one_notice():
    item = release(2, "3.80.2", 6)
    api = fake_api([item, dict(item)])
    assert watch.monitor(api, "owner/ghostfolio-degiro-sync", CONFIG) == [1]
    assert len(api.writes) == 1


def test_unusual_tags_are_not_inserted_as_body_markup():
    tag = "3.80.2` @everyone [inject](https://evil.invalid)"
    body = watch.notice_body(CONFIG, release(2, tag, 6), tag)
    assert "@everyone" not in body
    assert "[inject]" not in body
    assert "%40everyone" in body


@pytest.mark.parametrize("status", [302, 403, 500])
def test_github_failure_does_not_follow_redirect_or_expose_token(monkeypatch, status):
    from contextlib import nullcontext
    from types import SimpleNamespace
    monkeypatch.setenv("GITHUB_TOKEN", "TOKEN-PRIVATE-SENTINEL")
    session = SimpleNamespace(trust_env=True)
    def request(method, url, **options):
        assert url == "https://api.github.com/repos/owner/repo/releases"
        assert options["allow_redirects"] is False and options["timeout"] == (10, 30)
        assert session.trust_env is False
        return SimpleNamespace(status_code=status)
    session.request = request
    monkeypatch.setattr(watch.requests, "Session", lambda: nullcontext(session))
    with pytest.raises(RuntimeError) as error:
        watch.request("GET", "repos/owner/repo/releases")
    assert "TOKEN-PRIVATE-SENTINEL" not in str(error.value)


def test_pagination_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(watch, "request", lambda *a: [{}] * 100)
    with pytest.raises(RuntimeError, match="pagination limit"):
        watch.list_all("repos/owner/repo/issues?state=all")


def test_failed_notice_post_stops_without_duplicate_retry():
    api = fake_api([release(2, "3.80.2", 6), release(3, "3.80.3", 7)])
    attempts = []
    def failed(method, path, payload=None):
        if method == "GET":
            return api.releases[0]
        attempts.append(payload)
        raise RuntimeError("Synthetic POST failure")
    api.request = failed
    with pytest.raises(RuntimeError):
        watch.monitor(api, "owner/repo", CONFIG)
    assert len(attempts) == 1
