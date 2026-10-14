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


def test_registry_diagnostics_expose_status_only(monkeypatch, capsys):
    response = SimpleNamespace(status_code=403, text="SYNTHETIC-RESPONSE-SECRET")
    monkeypatch.setattr(release.requests, "Session", lambda: nullcontext(
        SimpleNamespace(get=lambda *args, **kwargs: response)))
    with pytest.raises(RuntimeError):
        release.registry_version_absent("owner/repo", "v0.2.0", "actor", "SYNTHETIC-TOKEN")
    captured = capsys.readouterr()
    assert captured.err == "Registry token endpoint HTTP 403\n"
    assert captured.out == ""


def test_registry_exception_is_reported_by_phase_without_secret(monkeypatch, tmp_path, capsys):
    import json
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event()))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_ACTOR", "actor")
    monkeypatch.setenv("GH_TOKEN", "SYNTHETIC-TOKEN")
    monkeypatch.setattr(release.sys, "argv", ["release_image.py", "--registry"])
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(release.subprocess, "check_output", lambda *args, **kwargs: "same-sha\n")
    def fail(*args):
        raise RuntimeError("SYNTHETIC-RESPONSE-SECRET")
    monkeypatch.setattr(release, "registry_version_absent", fail)
    with pytest.raises(SystemExit) as failure:
        release.main()
    assert str(failure.value) == (
        "Release preflight failed at registry authorization and version absence; version publication refused")
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("token_status,token,api_status,allowed", [
    (200, "registry-session", 200, True), (403, "unused", 200, False),
    (200, "", 200, False), (200, "bad token", 200, False),
    (200, "registry-session", 401, False), (200, "registry-session", 302, False)])
def test_registry_login_does_not_request_nonexistent_package(monkeypatch, capsys,
        token_status, token, api_status, allowed):
    calls = []
    session = SimpleNamespace(trust_env=True)
    def get(url, **options):
        calls.append(url)
        assert session.trust_env is False
        assert options["allow_redirects"] is False and options["timeout"] == (10, 30)
        if url == "https://ghcr.io/token":
            assert options["params"] == {"service": "ghcr.io"}
            assert options["auth"] == ("actor", "SYNTHETIC-TOKEN")
            return SimpleNamespace(status_code=token_status, json=lambda: {"token": token})
        assert url == "https://ghcr.io/v2/"
        assert options["headers"] == {"Authorization": "Bearer registry-session"}
        return SimpleNamespace(status_code=api_status)
    session.get = get
    monkeypatch.setattr(release.requests, "Session", lambda: nullcontext(session))
    if allowed:
        release.registry_login("actor", "SYNTHETIC-TOKEN")
    else:
        with pytest.raises(RuntimeError):
            release.registry_login("actor", "SYNTHETIC-TOKEN")
    expected_calls = 2 if token_status == 200 and token == "registry-session" else 1
    assert len(calls) == expected_calls
    diagnostics = capsys.readouterr()
    assert diagnostics.out == "" and "SYNTHETIC-TOKEN" not in diagnostics.err
    assert "registry-session" not in diagnostics.err


def test_release_manifest_requires_both_native_gates_and_no_pr_publication():
    workflow = yaml.safe_load(Path(".github/workflows/release-image.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"release": {"types": ["published"]}}
    jobs = workflow["jobs"]
    assert any(step.get("run") == "python scripts/release_image.py --registry-login"
               for step in jobs["preflight"]["steps"])
    assert jobs["manifest"]["needs"] == ["preflight", "native-image"]
    guard = next(i for i, step in enumerate(jobs["manifest"]["steps"])
                 if step.get("run") == "python scripts/release_image.py --registry")
    publish = next(i for i, step in enumerate(jobs["manifest"]["steps"])
                   if "Assemble version manifest" in step.get("name", ""))
    assert guard < publish
    assert {item["arch"] for item in jobs["native-image"]["strategy"]["matrix"]["include"]} == {"amd64", "arm64"}
    steps = jobs["native-image"]["steps"]
    smoke = next(i for i, step in enumerate(steps) if "smoke_container.py" in step.get("run", ""))
    push = next(i for i, step in enumerate(steps) if step.get("id") == "image")
    assert smoke < push and steps[push]["with"]["provenance"] == "mode=max"
    assert steps[push]["with"]["sbom"] is True
    verification = next(step for step in steps if "Verify publication" in step.get("name", ""))
    assert 'scripts/verify_release_image.py' in verification["run"]
    assert 'containerimage.config.digest' not in verification["run"]
    promotion = next(step for step in jobs["manifest"]["steps"] if "Promote" in step.get("name", ""))
    assert promotion["if"] == "needs.preflight.outputs.prerelease == 'false'"
    assert 'releases/latest' in promotion["run"]
    base = yaml.safe_load(Path("compose.yaml").read_text())["services"]["degiro-sync"]
    assert "build" not in base
    assert base["image"] == "${DEGIRO_IMAGE:-ghcr.io/flowcool/ghostfolio-degiro-sync:v0.4.1}"
    assert base["restart"] == "${RESTART_POLICY:-no}"
    contributor = yaml.safe_load(Path("compose.build.yaml").read_text())["services"]["degiro-sync"]
    assert contributor["build"]["context"] == "." and contributor["pull_policy"] == "build"
