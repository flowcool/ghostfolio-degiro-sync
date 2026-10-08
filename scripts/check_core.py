#!/usr/bin/env python3
"""Verify the immutable core against its pinned IBKR Git source."""

import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_provenance(path):
    blocks = re.findall(r"^```yaml\n(.*?)^```$", path.read_text(), re.M | re.S)
    if len(blocks) != 1:
        raise RuntimeError("Expected one authoritative YAML provenance block")
    data = yaml.safe_load(blocks[0])
    if not isinstance(data, dict) or data.get("format") != 1:
        raise RuntimeError("Unsupported core provenance format")
    if data.get("repository") != "https://github.com/flowcool/ghostfolio-ibkr-sync.git":
        raise RuntimeError("Unexpected canonical core repository")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("commit", ""))):
        raise RuntimeError("Core source requires a full commit SHA")
    if data.get("source_path") != "ibkr_to_ghostfolio.py":
        raise RuntimeError("Unexpected canonical source path")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("source_sha256", ""))):
        raise RuntimeError("Invalid source blob hash")
    for field in ("imports", "constants", "functions"):
        items = data.get(field)
        if (not isinstance(items, list) or not items
                or any(not isinstance(item, str) or not item.strip() for item in items)
                or len(set(items)) != len(items)):
            raise RuntimeError(f"Invalid provenance {field}")
    return data


def git_bytes(source, *args):
    result = subprocess.run(["git", "-C", str(source), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=120, check=False)
    if result.returncode:
        raise RuntimeError("Cannot read canonical Git source")
    return result.stdout


def project_core(source_bytes, provenance):
    """Locate units with AST, then preserve their actual bytes, not AST output."""
    if hashlib.sha256(source_bytes).hexdigest() != provenance["source_sha256"]:
        raise RuntimeError("Canonical source blob does not match provenance hash")
    tree = ast.parse(source_bytes)
    lines = source_bytes.splitlines(keepends=True)
    available = {}
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        body = b"".join(lines[start - 1:node.end_lineno])
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            key = ("imports", body.decode().strip())
        elif isinstance(node, ast.FunctionDef):
            key = ("functions", node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            key = ("constants", node.targets[0].id)
        else:
            continue
        if key in available:
            raise RuntimeError(f"Ambiguous canonical unit: {key[1]}")
        available[key] = (start, body)
    selected = []
    for field in ("imports", "constants", "functions"):
        for name in provenance[field]:
            key = (field, name)
            if key not in available:
                raise RuntimeError(f"Missing canonical {field} unit: {name}")
            selected.append(available[key])
    return b"\n\n".join(body for _, body in sorted(selected))


def verify_core(source_bytes, provenance, target):
    expected = project_core(source_bytes, provenance)
    if target.read_bytes() != expected:
        raise RuntimeError("ghostfolio_core.py differs from pinned canonical bytes")
    return hashlib.sha256(expected).hexdigest()


def report_main(provenance, main_sha):
    if not re.fullmatch(r"[0-9a-f]{40}", main_sha):
        raise RuntimeError("Invalid canonical main SHA")
    if main_sha == provenance["commit"]:
        print(f"IBKR main matches core pin: {main_sha}")
        return False
    message = (f"IBKR main differs from core pin: {main_sha} vs {provenance['commit']}. "
               "Review and propagate manually using CORE_PROVENANCE.md; no auto-sync.")
    print(f"::warning title=IBKR core propagation required::{message}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(f"\n### IBKR core propagation required\n\n{message}\n")
    return True


def check_source(source, provenance, target, write=False, check_main=False, main_ref="refs/heads/main"):
    source_bytes = git_bytes(source, "show", f"{provenance['commit']}:{provenance['source_path']}")
    expected = project_core(source_bytes, provenance)
    if check_main:
        main_sha = git_bytes(source, "rev-parse", "--verify", main_ref).decode().strip()
        report_main(provenance, main_sha)
    if write:
        target.write_bytes(expected)
        print("Regenerated core explicitly; review the diff before an authorized commit")
    digest = verify_core(source_bytes, provenance, target)
    print(f"Core byte integrity OK: {digest}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Existing canonical Git checkout (read-only)")
    parser.add_argument("--provenance", type=Path, default=ROOT / "CORE_PROVENANCE.md")
    parser.add_argument("--target", type=Path, default=ROOT / "ghostfolio_core.py")
    parser.add_argument("--write", action="store_true", help="Explicit human-reviewed regeneration")
    parser.add_argument("--check-main", action="store_true", help="Signal canonical main SHA mismatch")
    parser.add_argument("--main-ref", default="refs/heads/main")
    args = parser.parse_args(argv)
    provenance = read_provenance(args.provenance)
    if args.source:
        check_source(args.source, provenance, args.target, args.write, args.check_main, args.main_ref)
    else:
        with tempfile.TemporaryDirectory(prefix="degiro-canonical-core.") as scratch:
            source = Path(scratch) / "ibkr.git"
            subprocess.run(["git", "clone", "--bare", "--depth=1", "--single-branch",
                            "--branch=main", provenance["repository"], str(source)],
                           check=True, timeout=120, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(source), "fetch", "--depth=1", "origin",
                            provenance["commit"]], check=True, timeout=120,
                           stdout=subprocess.DEVNULL)
            check_source(source, provenance, args.target, args.write, args.check_main, args.main_ref)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, SyntaxError, yaml.YAMLError,
            subprocess.SubprocessError) as error:
        print(f"Core check failed: {error}", file=sys.stderr)
        sys.exit(1)
