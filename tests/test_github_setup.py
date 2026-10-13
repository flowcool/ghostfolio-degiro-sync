"""Offline checks for repository bootstrap policies; never contact GitHub."""

import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "github_setup", Path(__file__).resolve().parents[1] / "scripts/configure_github.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_preview_never_mutates_and_rules_require_only_available_checks(monkeypatch):
    calls = []

    def api(endpoint, method="GET", payload=None):
        calls.append((endpoint, method, payload))
        assert method == "GET"
        if endpoint == setup.SOURCE:
            return {**{key: False for key in (
                "allow_merge_commit", "allow_squash_merge", "allow_rebase_merge",
                "delete_branch_on_merge", "allow_auto_merge", "has_issues",
                "has_projects", "has_wiki", "web_commit_signoff_required")},
                "security_and_analysis": {}}
        if endpoint == setup.TARGET:
            return {"size": 0}
        if endpoint.endswith("immutable-releases"):
            return {"enabled": False}
        if endpoint == setup.TARGET + "/rulesets":
            return []
        if endpoint == setup.SOURCE + "/rulesets":
            return [{"id": 1}]
        if endpoint.endswith("rulesets/1"):
            return {"name": "Main", "target": "branch", "enforcement": "active",
                    "conditions": {}, "bypass_actors": [], "rules": [
                        {"type": "required_status_checks", "parameters": {
                            "required_status_checks": [{"context": "test"},
                                                       {"context": "container-check (amd64)"}]}}]}
        if "/labels" in endpoint:
            return []
        return {}

    monkeypatch.setattr(setup, "api", api)
    rules = setup.configure()
    params = rules[0]["rules"][0]["parameters"]
    assert params["do_not_enforce_on_create"] is True
    assert [row["context"] for row in params["required_status_checks"]] == [
        "test", "container-check (ubuntu-24.04, amd64)",
        "container-check (ubuntu-24.04-arm, arm64)", "core-integrity"]
    assert all(row["integration_id"] == 15368
               for row in params["required_status_checks"][1:])
    assert all(method == "GET" for _, method, _ in calls)


@pytest.mark.parametrize("current_status", ["enabled", "disabled"])
def test_apply_preserves_local_security_pr_owner_and_keeps_alerts(monkeypatch, current_status):
    calls = []

    def api(endpoint, method="GET", payload=None):
        calls.append((endpoint, method, payload))
        if method != "GET":
            return None
        if endpoint == setup.SOURCE:
            return {**{key: False for key in (
                "allow_merge_commit", "allow_squash_merge", "allow_rebase_merge",
                "delete_branch_on_merge", "allow_auto_merge", "has_issues",
                "has_projects", "has_wiki", "web_commit_signoff_required")},
                "security_and_analysis": {
                    "dependabot_security_updates": {"status": "enabled"},
                    "secret_scanning": {"status": "enabled"}}}
        if endpoint == setup.TARGET:
            return {"size": 1, "security_and_analysis": {
                "dependabot_security_updates": {"status": current_status}}}
        if endpoint.endswith("immutable-releases"):
            return {"enabled": False}
        if endpoint.endswith(("/rulesets", "/labels?per_page=100")):
            return []
        return {}

    monkeypatch.setattr(setup, "api", api)
    setup.configure(apply=True)
    patch = next(payload for endpoint, method, payload in calls
                 if endpoint == setup.TARGET and method == "PATCH")
    assert patch["security_and_analysis"] == {"secret_scanning": {"status": "enabled"}}
    assert not any(endpoint.endswith("/automated-security-fixes") for endpoint, _, _ in calls)
    assert (setup.TARGET + "/vulnerability-alerts", "PUT", None) in calls
