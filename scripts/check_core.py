#!/usr/bin/env python3
"""Verify the immutable core against its pinned IBKR Git source."""

import argparse
import ast
import builtins
import symtable
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
    if not isinstance(data, dict) or data.get("format") not in (1, 2):
        raise RuntimeError("Unsupported core provenance format")
    if data.get("repository") != "https://github.com/flowcool/ghostfolio-ibkr-sync.git":
        raise RuntimeError("Unexpected canonical core repository")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("commit", ""))):
        raise RuntimeError("Core source requires a full commit SHA")
    if data["format"] == 1:
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
    else:
        sources = data.get("sources")
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(item, dict) or set(item) != {"path", "sha256"}
                    or not isinstance(item["path"], str)
                    or re.fullmatch(r"[A-Za-z0-9_./-]+\.py", item["path"]) is None
                    or item["path"].startswith(("/", "-")) or ".." in item["path"].split("/")
                    or re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])) is None
                    for item in sources)):
            raise RuntimeError("Invalid provenance sources")
        paths = [item["path"] for item in sources]
        if len(set(paths)) != len(paths):
            raise RuntimeError("Duplicate provenance source")
        for field in ("imports", "constants", "functions"):
            units = data.get(field)
            if (not isinstance(units, list) or not units
                    or any(not isinstance(unit, dict) or set(unit) != {"source", "name"}
                        or unit["source"] not in paths or not isinstance(unit["name"], str)
                        or not unit["name"].strip() for unit in units)
                    or len({(unit["source"], unit["name"]) for unit in units}) != len(units)):
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
    if provenance["format"] == 2:
        return project_multi_core(source_bytes, provenance)
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


def bound_names(node):
    if isinstance(node, ast.Import):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if any(alias.name == "*" for alias in node.names):
            raise RuntimeError("Undeclared wildcard import dependency")
        return [alias.asname or alias.name for alias in node.names]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [name.id for target in node.targets for name in ast.walk(target) if isinstance(name, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def verify_static_closure(body):
    """Resolve lexical globals and lazy annotation names without importing code."""
    tree = ast.parse(body)
    defined = {name for node in tree.body for name in bound_names(node)}
    available = defined | set(dir(builtins)) | {"__name__", "__doc__", "__annotations__"}
    referenced = set()
    def visit(table):
        for symbol in table.get_symbols():
            if symbol.is_referenced() and (table.get_type() == "module" or symbol.is_global()):
                referenced.add(symbol.get_name())
        for child in table.get_children():
            visit(child)
    visit(symtable.symtable(body.decode(), "projected_core", "exec"))
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            # Python 3.14 delays annotation evaluation; inspect strings too.
            for value in ast.walk(annotation):
                if isinstance(value, ast.Name):
                    referenced.add(value.id)
                elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                    referenced.update(n.id for n in ast.walk(ast.parse(value.value, mode="eval"))
                                      if isinstance(n, ast.Name))
    missing = referenced - available
    if missing:
        raise RuntimeError("Unresolved projected dependency: " + ", ".join(sorted(missing)))


def project_multi_core(sources, provenance):
    available = {}
    for source_index, source in enumerate(provenance["sources"]):
        path = source["path"]
        body = sources[path]
        if hashlib.sha256(body).hexdigest() != source["sha256"]:
            raise RuntimeError("Canonical source blob does not match provenance hash")
        lines = body.splitlines(keepends=True)
        for node in ast.parse(body).body:
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            raw = b"".join(lines[start - 1:node.end_lineno])
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                field, name = "imports", raw.decode().strip()
            elif isinstance(node, ast.FunctionDef):
                field, name = "functions", node.name
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                field, name = "constants", node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                field, name = "constants", node.target.id
            else:
                continue
            key = (path, field, name)
            if key in available:
                raise RuntimeError("Ambiguous canonical unit: " + name)
            available[key] = (source_index, start, raw, node)
    selected, names = [], set()
    for field in ("imports", "constants", "functions"):
        group = []
        for unit in provenance[field]:
            key = (unit["source"], field, unit["name"])
            if key not in available:
                raise RuntimeError(f"Missing canonical {field} unit: {unit['name']}")
            source_index, start, raw, node = available[key]
            bound = bound_names(node)
            if names.intersection(bound):
                raise RuntimeError("Undeclared projected name collision")
            names.update(bound)
            group.append((source_index, start, raw))
        selected.extend(raw for _, _, raw in sorted(group))
    result = b"\n\n".join(selected)
    verify_static_closure(result)
    return result


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
    if provenance["format"] == 1:
        source_bytes = git_bytes(source, "show", f"{provenance['commit']}:{provenance['source_path']}")
    else:
        source_bytes = {item["path"]: git_bytes(source, "show", f"{provenance['commit']}:{item['path']}")
                        for item in provenance["sources"]}
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
