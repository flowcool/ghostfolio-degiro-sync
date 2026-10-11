"""Review notices for source pins; never propagate upstream code automatically."""
import os
import sys
import requests
from pathlib import Path
import re
from urllib.parse import quote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def fixture_image_pins(root=ROOT):
    provenance = yaml.safe_load((root / "tests/fixtures/degiro_v3_transition.yaml").read_text())["provenance"]
    image = provenance["runtime_image"]
    match = re.fullmatch(r"node:([A-Za-z0-9_.-]+)@(sha256:[0-9a-f]{64})", image)
    if not match:
        raise ValueError("Invalid fixture image provenance")
    return [{"image": "node", "tag": match[1], "commit": match[2]}]


def fixture_image_digest(pin):
    if pin["image"] != "node" or not re.fullmatch(r"[A-Za-z0-9_.-]+", pin["tag"]):
        raise ValueError("Invalid fixture image tag")
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get("https://hub.docker.com/v2/repositories/library/node/tags/" + pin["tag"],
                timeout=(10, 30), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError
            digest = response.json()["digest"]
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError
            return digest
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise RuntimeError("Fixture image metadata unavailable") from None


def monitor(api, repository, pins):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid destination repository")
    pending = []
    unique = {(pin.get("repository", pin.get("image")), pin["commit"]): pin for pin in pins}
    for pin in unique.values():
        if "image" in pin:
            latest = fixture_image_digest(pin)
            if latest != pin["commit"]:
                pending.append((pin, latest, f"<!-- upstream-image:{pin['image']}:{pin['tag']}:{latest} -->"))
            continue
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
        if "image" in pin:
            upstream = f"{pin['image']}:{pin['tag']}"
            body = "\n".join([marker, "Contributor fixture image differs from its recorded digest.", "",
                f"Reviewed: `{pin['commit']}`", f"Observed: `{latest}`", "",
                "[Official Node image](https://hub.docker.com/_/node)", "",
                "- [ ] Review image/runtime security and the native CSV converter fixture.",
                "- [ ] Regenerate synthetic evidence and provenance deliberately before adopting.",
                "This notice does not repin, rebuild, deploy or access financial accounts.",
                "Closing acknowledges this digest; the watch does not reopen it."])
        else:
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
    monitor(github_api(), os.environ["GITHUB_REPOSITORY"], source_pins() + fixture_image_pins())
