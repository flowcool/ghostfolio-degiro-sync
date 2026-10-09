"""Offline regressions for exact owned-resource cleanup after converter failure."""
import subprocess
from types import SimpleNamespace

import pytest

from scripts import check_v3_transition as bench


IDENTITY = 'a' * 64
IMAGE = 'degiro-v3-reproduction:synthetic-owned'


def cleanup_probe(tmp_path, monkeypatch, failure=None, identity=IDENTITY):
    cid = tmp_path / 'converter.cid'
    cid.write_text(identity)
    calls = []

    def execute(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs == {'capture_output': True, 'timeout': 30}
        if arguments[:3] == ['docker', 'rm', '-f']:
            if isinstance(failure, Exception):
                raise failure
            return SimpleNamespace(returncode=1 if failure else 0,
                                   stderr=failure or b'', stdout=b'')
        return SimpleNamespace(returncode=0, stderr=b'', stdout=b'')

    monkeypatch.setattr(bench.subprocess, 'run', execute)
    return cid, calls


@pytest.mark.parametrize('prefix', ['Error response from daemon: ', 'Error: '])
def test_already_removed_exact_container_still_cleans_image(tmp_path, monkeypatch, prefix):
    cid, calls = cleanup_probe(tmp_path, monkeypatch,
                              (prefix + 'No such container: ' + IDENTITY + '\n').encode())
    bench.cleanup_owned_resources(cid, IMAGE, True, False)
    assert calls == [['docker', 'rm', '-f', IDENTITY], ['docker', 'image', 'rm', IMAGE]]


@pytest.mark.parametrize('failure', [
    b'permission denied',
    ('Error: No such container: ' + 'b' * 64).encode(),
    ('Error: No such container: ' + IDENTITY + '\npermission denied').encode(),
    subprocess.TimeoutExpired(['docker', 'rm'], 30),
])
def test_other_container_failures_propagate_after_image_cleanup(tmp_path, monkeypatch, failure):
    cid, calls = cleanup_probe(tmp_path, monkeypatch, failure)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        bench.cleanup_owned_resources(cid, IMAGE, True, False)
    assert calls[-1] == ['docker', 'image', 'rm', IMAGE]


def test_invalid_cid_cannot_remove_container_but_cleans_owned_image(tmp_path, monkeypatch):
    cid, calls = cleanup_probe(tmp_path, monkeypatch, identity='foreign-container')
    with pytest.raises(RuntimeError, match='Invalid owned'):
        bench.cleanup_owned_resources(cid, IMAGE, True, False)
    assert calls == [['docker', 'image', 'rm', IMAGE]]


@pytest.mark.parametrize('built,finished', [(False, True), (True, True), (True, False)])
def test_success_and_missing_cid_skip_container_cleanup(tmp_path, monkeypatch, built, finished):
    cid, calls = cleanup_probe(tmp_path, monkeypatch)
    if not finished:
        cid.unlink()
    bench.cleanup_owned_resources(cid, IMAGE, built, finished)
    assert calls == ([['docker', 'image', 'rm', IMAGE]] if built else [])
