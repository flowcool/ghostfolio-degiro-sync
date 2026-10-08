"""Offline checks for repository bootstrap policies; never contact GitHub."""

import importlib.util
from pathlib import Path


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
        "test", "core-integrity"]
    assert all(method == "GET" for _, method, _ in calls)
