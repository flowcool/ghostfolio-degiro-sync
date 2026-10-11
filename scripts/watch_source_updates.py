"""Review notices for source pins; never propagate upstream code automatically."""
import os
from pathlib import Path
import re
from urllib.parse import quote

import yaml

from check_core import read_provenance
from watch_ghostfolio_releases import github_api

ROOT = Path(__file__).resolve().parents[1]


def source_pins(root=ROOT):
    documents = [read_provenance(root / "CORE_PROVENANCE.md"),
        yaml.safe_load((root / "docs/connector-provenance.yaml").read_text()),
        yaml.safe_load((root / "tests/fixtures/degiro_v3_transition.yaml").read_text())["provenance"]]
    pins = []
    for document in documents:
        repository = document["repository"].removeprefix("https://github.com/").removesuffix(".git")
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                or not re.fullmatch(r"[0-9a-f]{40}", document["commit"])):
            raise ValueError("Invalid upstream source provenance")
        pins.append({"repository": repository, "commit": document["commit"]})
    return pins


def monitor(api, repository, pins):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid destination repository")
    pending = []
    unique = {(pin["repository"], pin["commit"]): pin for pin in pins}
    for pin in unique.values():
        upstream = pin["repository"]
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", upstream)
                or not re.fullmatch(r"[0-9a-f]{40}", pin["commit"])):
            raise ValueError("Invalid upstream source pin")
        metadata = api.request("GET", f"repos/{upstream}")
        branch = metadata["default_branch"]
        latest = api.request("GET", f"repos/{upstream}/commits/{quote(branch, safe='')}")["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", latest):
            raise ValueError("Invalid upstream source revision")
        if latest != pin["commit"]:
            marker = f"<!-- upstream-source:{upstream}:{latest} -->"
            pending.append((pin, latest, marker))
    if not pending:
        print("Reviewed source pins match upstream default branches")
        return []
    bodies = [issue.get("body") or "" for issue in api.list_all(f"repos/{repository}/issues?state=all")
              if "pull_request" not in issue]
    pending = [entry for entry in pending if not any(entry[2] in body for body in bodies)]
    if not pending:
        print("Source differences already have review notices")
        return []
    labels = {label["name"] for label in api.list_all(f"repos/{repository}/labels")}
    if "upstream-source" not in labels:
        api.request("POST", f"repos/{repository}/labels", {"name": "upstream-source", "color": "5319e7"})
    created = []
    for pin, latest, marker in pending[:10]:
        upstream = pin["repository"]
        body = "\n".join([marker, "Upstream source differs from the reviewed source pin.", "",
            f"Reviewed: `{pin['commit']}`", f"Observed: `{latest}`", "",
            f"[Compare source](https://github.com/{upstream}/compare/{pin['commit']}...{latest})", "",
            "- [ ] Review the consumed functions, connector contract or CSV converter changes.",
            "- [ ] Update offline fixtures and provenance only after compatibility review.",
            "- [ ] Record adoption or the reason to retain the current pin.", "",
            "This notice does not repin, regenerate, deploy or access financial accounts.",
            "Closing acknowledges this source revision; the watch does not reopen it."])
        issue = api.request("POST", f"repos/{repository}/issues", {
            "title": f"Review {upstream} source {latest[:12]}", "body": body,
            "labels": ["upstream-source"]})
        created.append(issue["number"])
    return created


if __name__ == "__main__":
    monitor(github_api(), os.environ["GITHUB_REPOSITORY"], source_pins())
