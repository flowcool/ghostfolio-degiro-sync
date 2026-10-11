"""Verify the native config in an attested published index against the tested image."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def native_manifest_digest(index, arch):
    matches = [entry.get("digest") for entry in index.get("manifests", [])
        if entry.get("platform", {}).get("os") == "linux"
        and entry.get("platform", {}).get("architecture") == arch]
    if len(matches) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0] or ""):
        raise RuntimeError("Exactly one native image manifest is required")
    return matches[0]


def verify(image, digest, arch):
    if (not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", image)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or arch not in ("amd64", "arm64")):
        raise RuntimeError("Invalid publication reference")
    def inspect(ref):
        return json.loads(subprocess.check_output(
            ["docker", "buildx", "imagetools", "inspect", "--raw", ref],
            text=True, timeout=60))
    index = inspect(image + "@" + digest)
    manifest = inspect(image + "@" + native_manifest_digest(index, arch))
    local = subprocess.check_output(["docker", "inspect", "--format", "{{.Id}}",
        "degiro-release:check"], text=True, timeout=15).strip()
    if manifest.get("config", {}).get("digest") != local:
        raise RuntimeError("Published native configuration differs from the tested image")
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--arch", required=True)
    args = parser.parse_args()
    digest = verify(args.image, args.digest, args.arch)
    Path("digests").mkdir(exist_ok=True)
    Path("digests", args.arch + ".txt").write_text(digest)


if __name__ == "__main__":
    main()
