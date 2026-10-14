"""Offline binary release-watch contracts; no real network or issue writes."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "dependency_watch", Path(__file__).parents[1] / "scripts/watch_dependency_releases.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

REPO = "owner/ghostfolio-degiro-sync"
PINS = [
    {"ecosystem": "github", "name": "aptible/supercronic", "version": "0.2.49"},
    {"ecosystem": "github", "name": "bitwarden/clients", "version": "2026.9.1", "tag_prefix": "cli-v"},
]


def fake_api(issues=None, releases=None):
    api = SimpleNamespace(issues=list(issues or []), writes=[], reads=[])
    api.releases = releases if releases is not None else {
        "aptible/supercronic": [{"tag_name": "v0.2.50"}],
        "bitwarden/clients": [{"tag_name": "cli-v2026.9.2"}],
    }

    def list_all(path):
        api.reads.append(path)
        if path.endswith("/issues?state=all"):
            return api.issues
        if path.endswith("/labels"):
            return [{"name": "dependency-release"}]
        if path.endswith("/releases"):
            return api.releases[path.removeprefix("repos/").removesuffix("/releases")]
        raise AssertionError(path)

    def request(method, path, payload=None):
        assert method == "POST" and path.endswith("/issues"), path
        api.writes.append(payload)
        issue = {"number": len(api.issues) + 1, "body": payload["body"]}
        api.issues.append(issue)
        return issue

    api.list_all, api.request = list_all, request
    return api


@pytest.mark.parametrize("pin,new_version", [(PINS[0], "0.2.50"), (PINS[1], "2026.9.2")])
def test_new_binary_opens_one_notice_and_closed_notice_is_not_duplicated(pin, new_version):
    api = fake_api()
    assert watch.monitor(api, REPO, [pin]) == [1]
    assert api.writes[0]["title"] == f"Review {pin['name']} {new_version} (pinned {pin['version']})"
    assert api.writes[0]["labels"] == ["dependency-release"]
    assert watch.release_page(pin, new_version) in api.writes[0]["body"]
    assert "architecture-checksum update" in api.writes[0]["body"]
    api.issues[0]["state"] = "closed"
    assert watch.monitor(api, REPO, [pin]) == []
    assert len(api.writes) == 1


@pytest.mark.parametrize("ecosystem,name", [("pypi", "requests"), ("npm", "apprise"),
                                          ("github", "owner/package")])
def test_package_updates_make_no_notices_or_metadata_reads(ecosystem, name):
    api = fake_api(releases={})
    assert watch.monitor(api, REPO, [{"ecosystem": ecosystem, "name": name, "version": "1.0"}]) == []
    assert api.writes == [] and api.reads == []


def test_packages_do_not_block_binary_notices():
    api = fake_api()
    packages = [{"ecosystem": "pypi", "name": "requests", "version": "1.0"},
                {"ecosystem": "npm", "name": "example", "version": "1.0"}]
    assert watch.monitor(api, REPO, packages + PINS) == [1, 2]
    assert [p["title"] for p in api.writes] == [
        "Review aptible/supercronic 0.2.50 (pinned 0.2.49)",
        "Review bitwarden/clients 2026.9.2 (pinned 2026.9.1)"]


def test_major_minor_patch_are_flagged():
    pin = PINS[0]
    assert "patch version change" in watch.notice_body(pin, {"version": "0.2.50"}, [])
    assert "minor version change" in watch.notice_body(pin, {"version": "0.3.0"}, [])
    assert "major version change: breaking changes are likely" in watch.notice_body(pin, {"version": "1.0"}, [])
    assert "patch version change" in watch.notice_body(dict(pin, version="2.0"), {"version": "2.0.1"}, [])


def test_equivalent_versions_get_one_notice_and_marker_matches_other_spelling():
    pin = dict(PINS[0], version="2.34.2")
    api = fake_api(releases={pin["name"]: [{"tag_name": "v" + v} for v in
                                         ["2.34.2", "2.34.2.0", "2.35", "2.35.0"]]})
    assert watch.monitor(api, REPO, [pin]) == [1]
    api.issues[0]["body"] = watch.release_marker(pin, "2.35")
    assert watch.monitor(api, REPO, [pin]) == []


def test_markers_are_scoped_to_component_and_pr_markers_are_ignored():
    api = fake_api(issues=[{"body": watch.release_marker(PINS[1], "0.2.50")},
                          {"body": watch.release_marker(PINS[0], "0.2.50"), "pull_request": {}}])
    assert len(watch.monitor(api, REPO, PINS[:1])) == 1


@pytest.mark.parametrize("pin", PINS)
def test_release_prefix_excludes_other_clients_drafts_prereleases_and_unstable_versions(pin):
    prefix = pin.get("tag_prefix", "v")
    api = fake_api(releases={pin["name"]: [
        {"tag_name": prefix + "9999.0"}, {"tag_name": prefix + "9999.1", "draft": True},
        {"tag_name": prefix + "9999.2", "prerelease": True},
        {"tag_name": prefix + "9999.3rc1"}, {"tag_name": "web-v9999.0"}, {"tag_name": "nightly"}]})
    assert len(watch.monitor(api, REPO, [pin])) == 1
    assert "9999.0" in api.writes[0]["title"]


def test_untrusted_timestamp_is_not_copied_as_markup():
    api = fake_api(releases={PINS[0]["name"]: [
        {"tag_name": "v0.2.50", "published_at": "@everyone [x](https://evil.invalid)"}]})
    watch.monitor(api, REPO, PINS[:1])
    body = api.writes[0]["body"]
    assert "evil.invalid" not in body and "@everyone" not in body
    assert "Published: unknown" in body


def test_new_issues_are_capped_and_remaining_releases_follow_next_run():
    pin = dict(PINS[0], version="1.0")
    api = fake_api(releases={pin["name"]: [{"tag_name": f"v1.{i}"} for i in range(15)]})
    assert len(watch.monitor(api, REPO, [pin])) == watch.MAX_NEW_ISSUES_PER_RUN
    assert len(watch.monitor(api, REPO, [pin])) == 4


def test_nothing_new_makes_no_issue_or_label_call():
    api = fake_api(releases={PINS[0]["name"]: [{"tag_name": "v0.2.49"}]})
    assert watch.monitor(api, REPO, PINS[:1]) == []
    assert api.writes == []
    assert api.reads == ["repos/aptible/supercronic/releases"]


def test_fetch_failure_stops_before_any_write():
    api = fake_api(releases={PINS[0]["name"]: [{"tag_name": "v0.2.50"}]})
    listing = api.list_all

    def broken(path):
        if "bitwarden/clients" in path:
            raise RuntimeError("Synthetic upstream failure")
        return listing(path)

    api.list_all = broken
    with pytest.raises(RuntimeError, match="Synthetic upstream failure"):
        watch.monitor(api, REPO, PINS)
    assert api.writes == []


def test_invalid_destination_repository_is_rejected():
    with pytest.raises(ValueError):
        watch.monitor(fake_api(), "not a repo", PINS)


def test_only_binary_pins_are_read_without_package_manifests(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python\nARG SUPERCRONIC_VERSION=v0.2.49\nARG BW_VERSION=2026.9.1\n")
    assert watch.read_pins(tmp_path) == PINS
    (tmp_path / "requirements.txt").write_text("requests>=999\n")
    (tmp_path / "requirements-dev.txt").write_text("unsupported package input\n")
    (tmp_path / "package.json").write_text('{"dependencies":{"example":"99999.0"}}')
    assert watch.read_pins(tmp_path) == PINS


def test_real_repository_has_only_supercronic_and_bitwarden_pins():
    pins = watch.read_pins()
    assert {p["name"] for p in pins} == {"aptible/supercronic", "bitwarden/clients"}
    assert all(p["ecosystem"] == "github" for p in pins)


@pytest.mark.parametrize("dockerfile", [
    "FROM python\n", "ARG SUPERCRONIC_VERSION=v0.2.49\n",
    "ARG BW_VERSION=2026.9.1\n",
    "ARG SUPERCRONIC_VERSION=v0.2.50rc1\nARG BW_VERSION=2026.9.1\n",
    "ARG SUPERCRONIC_VERSION=v0.2.49\nARG BW_VERSION=2026.9.2rc1\n"])
def test_missing_or_unstable_binary_pins_fail_loudly(tmp_path, dockerfile):
    (tmp_path / "Dockerfile").write_text(dockerfile)
    with pytest.raises(ValueError):
        watch.read_pins(tmp_path)
