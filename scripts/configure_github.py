#!/usr/bin/env python3
"""Mirror applicable IBKR GitHub settings; dry-run unless --apply is explicit."""

import argparse
import json
from pathlib import Path
import subprocess


SOURCE = "repos/flowcool/ghostfolio-ibkr-sync"
TARGET = "repos/flowcool/ghostfolio-degiro-sync"


def api(endpoint, method="GET", payload=None):
    args = ["gh", "api", endpoint, "--method", method]
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"GitHub configuration failed: {method} {endpoint}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def configure(apply=False, snapshot=None):
    source = api(SOURCE)
    fields = ("allow_merge_commit", "allow_squash_merge", "allow_rebase_merge",
              "delete_branch_on_merge", "allow_auto_merge", "has_issues",
              "has_projects", "has_wiki", "web_commit_signoff_required")
    settings = {key: source[key] for key in fields}
    if api(TARGET)["size"]:
        settings["default_branch"] = "main"
    settings["security_and_analysis"] = source["security_and_analysis"]
    changes = [(TARGET, "PATCH", settings)]
    for suffix in ("actions/permissions", "actions/permissions/workflow"):
        changes.append((f"{TARGET}/{suffix}", "PUT", api(f"{SOURCE}/{suffix}")))
    suffix = "immutable-releases"
    enabled = api(f"{SOURCE}/{suffix}")["enabled"]
    if api(f"{TARGET}/{suffix}")["enabled"] != enabled:
        changes.append((f"{TARGET}/{suffix}", "PUT" if enabled else "DELETE", None))
    suffix = "actions/permissions/fork-pr-contributor-approval"
    changes.append((f"{TARGET}/{suffix}", "PUT", api(f"{SOURCE}/{suffix}")))
    changes += [(f"{TARGET}/vulnerability-alerts", "PUT", None),
                (f"{TARGET}/automated-security-fixes", "PUT", None),
                (f"{TARGET}/private-vulnerability-reporting", "PUT", None)]
    existing = {row["name"]: row["id"] for row in api(f"{TARGET}/rulesets")}
    rules = []
    for row in api(f"{SOURCE}/rulesets"):
        original = api(f"{SOURCE}/rulesets/{row['id']}")
        rule = {key: original[key] for key in
                ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")}
        for item in rule["rules"]:
            if item["type"] == "required_status_checks":
                params = item["parameters"]
                # First branch creation is allowed; subsequent changes require a PR.
                params["do_not_enforce_on_create"] = True
                params["required_status_checks"] = [
                    check for check in params["required_status_checks"]
                    if not check["context"].startswith("container-check")]
                params["required_status_checks"].append(
                    {"context": "core-integrity", "integration_id": 15368})
        rules.append(rule)
        endpoint = f"{TARGET}/rulesets"
        method = "POST"
        if rule["name"] in existing:
            endpoint += f"/{existing[rule['name']]}"
            method = "PUT"
        changes.append((endpoint, method, rule))
    for label in api(f"{SOURCE}/labels?per_page=100"):
        changes.append((f"{TARGET}/labels", "POST",
                        {key: label[key] for key in ("name", "color", "description")}))
    if snapshot:
        before = {"repository": api(TARGET), "rulesets": [
            api(f"{TARGET}/rulesets/{row['id']}") for row in api(f"{TARGET}/rulesets")],
            "actions": api(f"{TARGET}/actions/permissions"),
            "workflow": api(f"{TARGET}/actions/permissions/workflow")}
        snapshot.write_text(json.dumps(before, indent=2) + "\n")
    print(f"{'Apply' if apply else 'Preview'}: {len(changes)} GitHub settings operations")
    for endpoint, method, payload in changes:
        if apply:
            if endpoint.endswith("/labels"):
                # Existing default labels are updated rather than duplicated.
                current = {row["name"] for row in api(f"{TARGET}/labels?per_page=100")}
                if payload["name"] in current:
                    from urllib.parse import quote
                    endpoint += "/" + quote(payload["name"], safe="")
                    method = "PATCH"
            api(endpoint, method, payload)
        print(f"{method} {endpoint}")
    return rules


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    configure(args.apply, args.snapshot)
