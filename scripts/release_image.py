"""Fail-closed release and registry guards; version tags are single publication."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests


def release_metadata(event):
    release = event.get("release", {})
    tag = release.get("tag_name", "")
    if (event.get("action") != "published" or release.get("draft")
            or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.[1-9][0-9]*)?", tag)
            or type(release.get("prerelease")) is not bool
            or release["prerelease"] != ("-" in tag)):
        raise RuntimeError("A published semantic-version release is required")
    return tag, release["prerelease"]


def highest_candidate_source(tag, tags, resolve):
    """Stable promotion must use the highest numbered candidate's source."""
    if "-" in tag:
        return
    candidates = []
    for candidate in tags:
        match = re.fullmatch(re.escape(tag) + r"-rc\.([1-9][0-9]*)", candidate)
        if match:
            candidates.append((int(match[1]), candidate))
    if candidates:
        candidate = max(candidates)[1]
        if resolve(tag) != resolve(candidate):
            raise RuntimeError(f"Stable {tag} differs from highest candidate {candidate}")


def registry_version_absent(repository, tag, username, password):
    """Only an authenticated missing manifest or repository allows initial publication."""
    if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repository):
        raise RuntimeError("Invalid release repository")
    with requests.Session() as session:
        session.trust_env = False
        response = session.get("https://ghcr.io/token", params={"service": "ghcr.io",
            "scope": f"repository:{repository}:pull,push"}, auth=(username, password),
            timeout=(10, 30), allow_redirects=False)
        print(f"Registry token endpoint HTTP {response.status_code}", file=sys.stderr)
        if response.status_code != 200:
            raise RuntimeError("Registry authorization failed")
        token = response.json().get("token")
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise RuntimeError("Registry authorization failed")
        response = session.get(f"https://ghcr.io/v2/{repository}/manifests/{tag}",
            headers={"Authorization": "Bearer " + token,
                "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"},
            timeout=(10, 30), allow_redirects=False)
        print(f"Registry version manifest HTTP {response.status_code}", file=sys.stderr)
        if response.status_code == 200:
            raise RuntimeError("Version image already exists; publication refused")
        body = response.json()
        errors = body.get("errors", []) if isinstance(body, dict) else []
        if response.status_code != 404 or not errors or any(
                error.get("code") not in ("MANIFEST_UNKNOWN", "NAME_UNKNOWN") for error in errors):
            raise RuntimeError("Registry absence could not be proven")


def registry_login(username, password):
    """Authenticate before builds without reading a package that may not exist yet."""
    with requests.Session() as session:
        session.trust_env = False
        response = session.get("https://ghcr.io/token", params={"service": "ghcr.io"},
            auth=(username, password), timeout=(10, 30), allow_redirects=False)
        print(f"Registry login token endpoint HTTP {response.status_code}", file=sys.stderr)
        if response.status_code != 200:
            raise RuntimeError("Registry authorization failed")
        token = response.json().get("token")
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise RuntimeError("Registry authorization failed")
        response = session.get("https://ghcr.io/v2/",
            headers={"Authorization": "Bearer " + token}, timeout=(10, 30), allow_redirects=False)
        print(f"Registry login API HTTP {response.status_code}", file=sys.stderr)
        if response.status_code != 200:
            raise RuntimeError("Registry authorization failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", action="store_true")
    parser.add_argument("--registry-login", action="store_true")
    args = parser.parse_args()
    phase = "release metadata"
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        tag, prerelease = release_metadata(event)
        phase = "release Git ancestry and tag"
        subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        # Checkout must resolve this release tag, not an arbitrary workflow ref.
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=15).strip()
        tagged = subprocess.check_output(["git", "rev-parse", tag + "^{commit}"], text=True, timeout=15).strip()
        if head != tagged:
            raise RuntimeError("Release checkout does not match tag")
        phase = "highest candidate source"
        tags = subprocess.check_output(["git", "tag", "--list", tag + "-rc.*"],
                                       text=True, timeout=15).splitlines()
        def resolve(value):
            return subprocess.check_output(["git", "rev-parse", value + "^{commit}"],
                                           text=True, timeout=15).strip()
        highest_candidate_source(tag, tags, resolve)
        if args.registry_login:
            phase = "registry login"
            registry_login(os.environ["GITHUB_ACTOR"], os.environ["GH_TOKEN"])
        if args.registry:
            phase = "registry authorization and version absence"
            registry_version_absent(os.environ["GITHUB_REPOSITORY"].lower(), tag,
                                    os.environ["GITHUB_ACTOR"], os.environ["GH_TOKEN"])
        phase = "workflow output"
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"tag={tag}\nprerelease={str(prerelease).lower()}\n")
    except RuntimeError as error:
        if phase == "highest candidate source":
            raise SystemExit(str(error)) from None
        raise SystemExit(f"Release preflight failed at {phase}; version publication refused") from None
    except Exception:
        raise SystemExit(f"Release preflight failed at {phase}; version publication refused") from None


if __name__ == "__main__":
    main()
