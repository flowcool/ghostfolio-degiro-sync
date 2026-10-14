"""Compose default and README image pins name one stable release, so Renovate bumps them together."""
from pathlib import Path
import re

import pytest

IMAGE = "ghcr.io/flowcool/ghostfolio-degiro-sync"
# The tag is optional so a bare reference (implicit tag) is caught and rejected.
PIN = re.compile(re.escape(IMAGE) + r"(?![\w./-])(?::([^\s}`'\"|]+))?")
STABLE = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


def single_stable_pin(texts):
    found = {pin for text in texts for pin in PIN.findall(text)}
    assert len(found) == 1, f"expected one image pin, found {sorted(found)}"
    pin = found.pop()
    assert STABLE.fullmatch(pin), f"pin is not a stable vX.Y.Z tag: {pin}"
    return pin


def test_compose_default_and_readme_pins_match():
    single_stable_pin([Path("compose.yaml").read_text(encoding="utf-8"),
                       Path("README.md").read_text(encoding="utf-8")])


def test_mismatched_readme_pin_fails():
    with pytest.raises(AssertionError, match="expected one image pin"):
        single_stable_pin([f"image: ${{DEGIRO_IMAGE:-{IMAGE}:v0.4.1}}\n", f"| `{IMAGE}:v0.4.0` |\n"])


def test_prerelease_pin_fails():
    with pytest.raises(AssertionError, match="not a stable"):
        single_stable_pin([f"image: {IMAGE}:v0.5.0-rc.1\n"])


def test_bare_reference_fails():
    with pytest.raises(AssertionError):
        single_stable_pin([f"image: {IMAGE}\n"])


def test_sub_path_image_is_ignored():
    assert single_stable_pin([f"image: {IMAGE}:v0.4.1\n", f"image: {IMAGE}/sidecar:v1\n"]) == "v0.4.1"
