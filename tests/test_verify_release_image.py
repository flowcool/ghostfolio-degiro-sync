"""Published index verification rejects ambiguity and untested native configurations."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("verify_release_image", Path("scripts/verify_release_image.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
DIGEST = "sha256:" + "a" * 64
NATIVE = "sha256:" + "b" * 64
CONFIG = "sha256:" + "c" * 64


def index(arch="amd64"):
    return {"manifests": [{"digest": NATIVE, "platform": {"os": "linux", "architecture": arch}},
        {"digest": "sha256:" + "d" * 64, "platform": {"os": "unknown", "architecture": "unknown"}}]}


@pytest.mark.parametrize("arch", ["amd64", "arm64"])
@pytest.mark.parametrize("matches", [True, False])
def test_exact_published_native_config_matches_validated_local_image(monkeypatch, arch, matches):
    calls = []
    def output(command, **options):
        calls.append(command)
        assert options["text"] is True and options["timeout"] <= 60
        if command[:3] == ["docker", "inspect", "--format"]:
            return CONFIG + "\n"
        assert command[:5] == ["docker", "buildx", "imagetools", "inspect", "--raw"]
        if command[-1].endswith(DIGEST):
            return json.dumps(index(arch))
        assert command[-1] == "ghcr.io/owner/repo@" + NATIVE
        return json.dumps({"config": {"digest": CONFIG if matches else DIGEST}})
    monkeypatch.setattr(release.subprocess, "check_output", output)
    if matches:
        assert release.verify("ghcr.io/owner/repo", DIGEST, arch) == DIGEST
    else:
        with pytest.raises(RuntimeError, match="differs"):
            release.verify("ghcr.io/owner/repo", DIGEST, arch)
    assert len(calls) == 3


@pytest.mark.parametrize("change", ["missing", "duplicate", "malformed", "other-platform"])
def test_native_manifest_must_be_unique_valid_and_correct_platform(change):
    data = index()
    if change == "missing":
        data = {}
    elif change == "duplicate":
        data["manifests"].append(data["manifests"][0])
    elif change == "malformed":
        data["manifests"][0]["digest"] = "untrusted;command"
    else:
        data["manifests"][0]["platform"]["os"] = "windows"
    with pytest.raises(RuntimeError):
        release.native_manifest_digest(data, "amd64")


@pytest.mark.parametrize("image,digest,arch", [
    ("evil.example/owner/repo", DIGEST, "amd64"),
    ("ghcr.io/owner/repo", "invalid", "amd64"),
    ("ghcr.io/owner/repo", DIGEST, "unknown")])
def test_invalid_reference_never_executes_docker(monkeypatch, image, digest, arch):
    monkeypatch.setattr(release.subprocess, "check_output", lambda *args, **kwargs: pytest.fail("Unexpected command"))
    with pytest.raises(RuntimeError):
        release.verify(image, digest, arch)


@pytest.mark.parametrize("succeeds", [True, False])
def test_cli_only_hands_verified_digest_to_manifest_job(monkeypatch, tmp_path, succeeds):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_release_image.py", "--image", "ghcr.io/owner/repo",
        "--digest", DIGEST, "--arch", "amd64"])
    def verify(image, digest, arch):
        assert (image, digest, arch) == ("ghcr.io/owner/repo", DIGEST, "amd64")
        if not succeeds:
            raise RuntimeError("Published configuration mismatch")
        return digest
    monkeypatch.setattr(release, "verify", verify)
    artifact = tmp_path / "digests" / "amd64.txt"
    if succeeds:
        release.main()
        assert artifact.read_text() == DIGEST
    else:
        with pytest.raises(RuntimeError):
            release.main()
        assert not artifact.exists()
