"""Offline mutation tests for canonical source projection and propagation signals."""

import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest


SPEC = importlib.util.spec_from_file_location(
    "core_guard", Path(__file__).resolve().parents[1] / "scripts/check_core.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

SOURCE = b'import logging\r\n\r\nlog = logging.getLogger(__name__)\r\n\r\ndef opaque_comment(row):\r\n    # Keep this comment and the original line endings.\r\n    return row["comment"]\r\n'


def provenance():
    return {"format": 1,
            "repository": "https://github.com/flowcool/ghostfolio-ibkr-sync.git",
            "commit": "1" * 40, "source_path": "ibkr_to_ghostfolio.py",
            "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
            "imports": ["import logging"], "constants": ["log"],
            "functions": ["opaque_comment"]}


def test_projection_preserves_function_bytes_and_crlf():
    expected = (b'import logging\r\n\n\nlog = logging.getLogger(__name__)\r\n\n\n'
                b'def opaque_comment(row):\r\n'
                b'    # Keep this comment and the original line endings.\r\n'
                b'    return row["comment"]\r\n')
    assert guard.project_core(SOURCE, provenance()) == expected


@pytest.mark.parametrize("changed", [
    lambda body: body.replace(b'return row["comment"]', b'return "DEGIRO#fake"'),
    lambda body: body.replace(b"    return", b"    return "),
    lambda body: body.replace(b"opaque_comment(row)", b"opaque_comment(row, broker=None)"),
    lambda body: body.replace(b"# Keep", b"# Change"),
    lambda body: body.replace(b"\r\n", b"\n"),
    lambda body: body + b"\nBROKER = 'DEGIRO'\n",
])
def test_core_drift_fails_even_if_only_whitespace_or_comments(tmp_path, changed):
    target = tmp_path / "core.py"
    target.write_bytes(changed(guard.project_core(SOURCE, provenance())))
    with pytest.raises(RuntimeError, match="differs from pinned canonical bytes"):
        guard.verify_core(SOURCE, provenance(), target)


def test_changed_source_blob_cannot_masquerade_as_pin():
    with pytest.raises(RuntimeError, match="source blob"):
        guard.project_core(SOURCE.replace(b"row", b"data"), provenance())


def test_missing_selected_unit_fails():
    data = {**provenance(), "functions": ["renamed_or_missing"]}
    with pytest.raises(RuntimeError, match="Missing canonical functions"):
        guard.project_core(SOURCE, data)


def test_provenance_is_one_authoritative_yaml_block(tmp_path):
    path = tmp_path / "PROVENANCE.md"
    path.write_text("```yaml\nformat: 1\n```\n```yaml\nformat: 1\n```\n")
    with pytest.raises(RuntimeError, match="one authoritative YAML"):
        guard.read_provenance(path)


@pytest.mark.parametrize("field,value", [
    ("commit", "main"), ("commit", "short-sha"),
    ("source_sha256", "bogus"), ("source_path", "../../elsewhere"),
    ("repository", "https://different.example/repo.git"),
    ("functions", []), ("functions", ["same", "same"]),
    ("constants", [None]), ("imports", "import logging"),
])
def test_invalid_provenance_rejected(tmp_path, field, value):
    data = {**provenance(), field: value}
    path = tmp_path / "PROVENANCE.md"
    path.write_text("```yaml\n" + guard.yaml.safe_dump(data) + "```\n")
    with pytest.raises(RuntimeError):
        guard.read_provenance(path)


def test_main_change_warns_without_changing_pin_or_core(tmp_path, monkeypatch, capsys):
    data = provenance()
    target = tmp_path / "core.py"
    body = guard.project_core(SOURCE, data)
    target.write_bytes(body)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def git_source(repo, *args):
        if args[0] == "show":
            assert args[1] == data["commit"] + ":ibkr_to_ghostfolio.py"
            return SOURCE
        assert args == ("rev-parse", "--verify", "refs/heads/main")
        return ("2" * 40 + "\n").encode()

    monkeypatch.setattr(guard, "git_bytes", git_source)
    guard.check_source(tmp_path, data, target, check_main=True)
    assert "::warning" in capsys.readouterr().out
    assert "propagate manually" in summary.read_text()
    assert data["commit"] == "1" * 40
    assert target.read_bytes() == body


def test_matching_main_is_clean(capsys):
    assert guard.report_main(provenance(), "1" * 40) is False
    assert "::warning" not in capsys.readouterr().out


def test_missing_main_is_failure_not_success(tmp_path, monkeypatch):
    target = tmp_path / "core.py"
    target.write_bytes(guard.project_core(SOURCE, provenance()))

    def git_source(repo, *args):
        if args[0] == "show":
            return SOURCE
        raise RuntimeError("Cannot read canonical Git source")

    monkeypatch.setattr(guard, "git_bytes", git_source)
    with pytest.raises(RuntimeError, match="canonical Git source"):
        guard.check_source(tmp_path, provenance(), target, check_main=True)


def test_regeneration_requires_explicit_write(tmp_path, monkeypatch):
    target = tmp_path / "core.py"
    target.write_bytes(b"modified locally\n")
    monkeypatch.setattr(guard, "git_bytes", lambda *args: SOURCE)
    with pytest.raises(RuntimeError, match="differs"):
        guard.check_source(tmp_path, provenance(), target)
    assert target.read_bytes() == b"modified locally\n"
    guard.check_source(tmp_path, provenance(), target, write=True)
    assert target.read_bytes() == guard.project_core(SOURCE, provenance())


def test_git_failure_is_closed_and_bounded(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 128, stdout=b"", stderr=b"missing")

    monkeypatch.setattr(guard.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="canonical Git source"):
        guard.git_bytes(tmp_path, "show", "1" * 40 + ":ibkr_to_ghostfolio.py")
    assert calls[0][1]["timeout"] == 120


def test_adapter_scaffold_sends_no_calls(monkeypatch):
    import degiro_to_ghostfolio as adapter

    def forbidden(*args, **kwargs):
        pytest.fail("Scaffold must not call Ghostfolio")

    for name in ("get", "post", "put", "delete"):
        monkeypatch.setattr(adapter.core.requests, name, forbidden)
    assert adapter.main() == 1
