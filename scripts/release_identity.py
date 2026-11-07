"""Pure release identity checks shared by image and publication commands."""
import re


STABLE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RC_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-rc\.([1-9][0-9]*)")


def release_identity(tag, commit):
    """Derive target software identity from the checked release tag and commit."""
    match = STABLE_TAG.fullmatch(tag) or RC_TAG.fullmatch(tag)
    if not match or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Exact release tag and full source commit required")
    return ".".join(match.group(1, 2, 3)), commit


def verify_image_identity(config, tag, commit, repository, arch):
    """Verify runtime and OCI identity; unsigned legacy metadata is not accepted."""
    version, revision = release_identity(tag, commit)
    image_config = config.get("config", {})
    labels = image_config.get("Labels", {})
    if (config.get("architecture") != arch or config.get("os") != "linux"
            or labels.get("org.opencontainers.image.revision") != revision
            or labels.get("org.opencontainers.image.source") != "https://github.com/" + repository
            or labels.get("org.opencontainers.image.version") != version):
        raise RuntimeError("Native source identity mismatch")
    runtime = {}
    for entry in image_config.get("Env", []):
        key, separator, value = entry.partition("=")
        if key in ("APP_VERSION", "APP_REVISION"):
            if not separator or key in runtime:
                raise RuntimeError("Ambiguous runtime image identity")
            runtime[key] = value
    if runtime != {"APP_VERSION": version, "APP_REVISION": revision}:
        raise RuntimeError("Runtime and OCI image identity mismatch")
