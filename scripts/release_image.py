"""Fail-closed release and registry guards; version tags are single publication."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import requests


def release_metadata(event):
    release = event.get("release", {})
    tag = release.get("tag_name", "")
    if (event.get("action") != "published" or release.get("draft")
            or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", tag)
            or type(release.get("prerelease")) is not bool
            or release["prerelease"] != ("-" in tag)):
        raise RuntimeError("A published semantic-version release is required")
    return tag, release["prerelease"]


def registry_version_absent(repository, tag, username, password):
    """Only an authenticated missing manifest or repository allows initial publication."""
    if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repository):
        raise RuntimeError("Invalid release repository")
    with requests.Session() as session:
        session.trust_env = False
        response = session.get("https://ghcr.io/token", params={"service": "ghcr.io",
            "scope": f"repository:{repository}:pull,push"}, auth=(username, password),
            timeout=(10, 30), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("Registry authorization failed")
        token = response.json().get("token")
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise RuntimeError("Registry authorization failed")
        response = session.get(f"https://ghcr.io/v2/{repository}/manifests/{tag}",
            headers={"Authorization": "Bearer " + token,
                "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"},
            timeout=(10, 30), allow_redirects=False)
        if response.status_code == 200:
            raise RuntimeError("Version image already exists; publication refused")
        body = response.json()
        errors = body.get("errors", []) if isinstance(body, dict) else []
        if response.status_code != 404 or not errors or any(
                error.get("code") not in ("MANIFEST_UNKNOWN", "NAME_UNKNOWN") for error in errors):
            raise RuntimeError("Registry absence could not be proven")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", action="store_true")
    args = parser.parse_args()
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        tag, prerelease = release_metadata(event)
        subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        # Checkout must resolve this release tag, not an arbitrary workflow ref.
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=15).strip()
        tagged = subprocess.check_output(["git", "rev-parse", tag + "^{commit}"], text=True, timeout=15).strip()
        if head != tagged:
            raise RuntimeError("Release checkout does not match tag")
        if args.registry:
            registry_version_absent(os.environ["GITHUB_REPOSITORY"].lower(), tag,
                                    os.environ["GITHUB_ACTOR"], os.environ["GH_TOKEN"])
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"tag={tag}\nprerelease={str(prerelease).lower()}\n")
    except Exception:
        raise SystemExit("Release preflight failed; version publication refused") from None


if __name__ == "__main__":
    main()
