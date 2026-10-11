"""Release immutability, provenance gates and registry failure policy."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location("release_image", Path("scripts/release_image.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def event(tag="v0.2.0", prerelease=False):
    return {"action": "published", "release": {"tag_name": tag, "prerelease": prerelease, "draft": False}}


def test_stable_and_prerelease_versions_are_distinct():
    assert release.release_metadata(event()) == ("v0.2.0", False)
    assert release.release_metadata(event("v0.2.0-rc.1", True)) == ("v0.2.0-rc.1", True)


@pytest.mark.parametrize("tag", ["latest", "v01.2.3", "v1.2", "v1.2.3/evil", "v1.2.3;echo x",
    "v1.2.3-", "v1.2.3-rc..1", "v1.2.3\n"])
def test_malformed_release_tags_rejected(tag):
    with pytest.raises(RuntimeError):
        release.release_metadata(event(tag))


@pytest.mark.parametrize("change", ["draft", "action", "mismatch", "missing-flag"])
def test_nonpublication_or_ambiguous_prerelease_rejected(change):
    data = event()
    if change == "draft":
        data["release"]["draft"] = True
    elif change == "action":
        data["action"] = "edited"
    elif change == "mismatch":
        data["release"]["prerelease"] = True
    else:
        del data["release"]["prerelease"]
    with pytest.raises(RuntimeError):
        release.release_metadata(data)


@pytest.mark.parametrize("status,body,allowed", [(200, {}, False),
    (404, {"errors": [{"code": "MANIFEST_UNKNOWN"}]}, True),
    (404, {"errors": [{"code": "NAME_UNKNOWN"}]}, True),
    (404, {}, False), (403, {"errors": [{"code": "DENIED"}]}, False),
    (401, {}, False), (500, {}, False), (302, {}, False),
    (404, {"errors": [{"code": "MANIFEST_UNKNOWN"}, {"code": "DENIED"}]}, False)])
def test_only_authorized_absence_allows_first_version_publication(monkeypatch, status, body, allowed):
    calls = []
    session = SimpleNamespace(trust_env=True)
    def get(url, **options):
        calls.append((url, options))
        assert options["allow_redirects"] is False and options["timeout"] == (10, 30)
        assert session.trust_env is False
        if url.endswith("/token"):
            assert options["auth"] == ("actor", "SYNTHETIC-TOKEN")
            return SimpleNamespace(status_code=200, json=lambda: {"token": "registry-session"})
        assert options["headers"]["Authorization"] == "Bearer registry-session"
        return SimpleNamespace(status_code=status, json=lambda: body)
    session.get = get
    monkeypatch.setattr(release.requests, "Session", lambda: nullcontext(session))
    if allowed:
        release.registry_version_absent("owner/repo", "v0.2.0", "actor", "SYNTHETIC-TOKEN")
    else:
        with pytest.raises(RuntimeError):
            release.registry_version_absent("owner/repo", "v0.2.0", "actor", "SYNTHETIC-TOKEN")
    assert len(calls) == 2


def test_unauthorized_registry_never_treated_as_absent(monkeypatch):
    calls = []
    def get(url, **options):
        calls.append(url)
        return SimpleNamespace(status_code=403)
    monkeypatch.setattr(release.requests, "Session", lambda: nullcontext(SimpleNamespace(get=get)))
    with pytest.raises(RuntimeError, match="authorization failed"):
        release.registry_version_absent("owner/repo", "v0.2.0", "actor", "SYNTHETIC-TOKEN")
    assert len(calls) == 1


def test_release_manifest_requires_both_native_gates_and_no_pr_publication():
    workflow = yaml.safe_load(Path(".github/workflows/release-image.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"release": {"types": ["published"]}}
    jobs = workflow["jobs"]
    assert jobs["manifest"]["needs"] == ["preflight", "native-image"]
    assert {item["arch"] for item in jobs["native-image"]["strategy"]["matrix"]["include"]} == {"amd64", "arm64"}
    steps = jobs["native-image"]["steps"]
    smoke = next(i for i, step in enumerate(steps) if "smoke_container.py" in step.get("run", ""))
    push = next(i for i, step in enumerate(steps) if step.get("id") == "image")
    assert smoke < push and steps[push]["with"]["provenance"] == "mode=max"
    assert steps[push]["with"]["sbom"] is True
    promotion = next(step for step in jobs["manifest"]["steps"] if "Promote" in step.get("name", ""))
    assert promotion["if"] == "needs.preflight.outputs.prerelease == 'false'"
    assert 'releases/latest' in promotion["run"]
    base = yaml.safe_load(Path("compose.yaml").read_text())["services"]["degiro-sync"]
    assert "build" not in base
    assert base["image"] == "${DEGIRO_IMAGE:-ghcr.io/flowcool/ghostfolio-degiro-sync:v0.2.0}"
    contributor = yaml.safe_load(Path("compose.build.yaml").read_text())["services"]["degiro-sync"]
    assert contributor["build"]["context"] == "." and contributor["pull_policy"] == "build"
