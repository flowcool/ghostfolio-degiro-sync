"""Offline owned-lab failure and recovery boundaries; no Docker or shared state."""
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest
import yaml

from scripts import lab_cleanup as lab

PROJECT = 'degiro-c13-' + 'a' * 10
IDS = {'container': '1' * 64, 'network': '2' * 64, 'image': 'sha256:' + '3' * 64}


@pytest.fixture
def state(tmp_path):
    record = tmp_path / 'ownership.yaml'
    result = {'project': PROJECT, 'record': record,
              'resources': {kind: [] for kind in lab.KINDS}, 'processes': []}
    lab.save_record(result)
    return result


@pytest.fixture
def engine(monkeypatch):
    calls = []
    resources = {kind: {identity} for kind, identity in IDS.items()}
    faults = {}

    def docker(kind, operation, *args):
        calls.append((kind, operation, args))
        if faults.get((kind, operation)):
            raise RuntimeError('SECRET_FAILURE_SENTINEL')
        if operation == 'ls':
            if '--filter' in args:
                assert args[args.index('--filter') + 1] == 'label=' + lab.LABEL + '=' + PROJECT
            return '\n'.join(sorted(resources[kind]))
        if operation == 'inspect':
            return json.dumps([{'Id': args[0], 'Internal': faults.get('internal', True),
                'Labels': {lab.LABEL: faults.get('owner', PROJECT)},
                'Config': {'Labels': {lab.LABEL: faults.get('owner', PROJECT)}}}])
        assert operation == 'rm'
        resources[kind].remove(args[-1])
        return ''

    monkeypatch.setattr(lab, 'docker', docker)
    return calls, resources, faults


def test_normal_cleanup_records_exact_ids_reverifies_and_removes_record(state, engine):
    assert lab.cleanup(state) == []
    assert not state['record'].exists()
    assert all(not identities for identities in engine[1].values())
    assert sum(operation == 'inspect' for _, operation, _ in engine[0]) == 3


@pytest.mark.parametrize('kind,operation', [('container', 'ls'), ('container', 'rm'),
                                         ('network', 'rm'), ('image', 'rm')])
def test_failure_does_not_skip_independent_cleanup_and_retains_private_record(state, engine, capsys, kind, operation):
    engine[2][(kind, operation)] = True
    assert lab.cleanup(state)
    for other in lab.KINDS:
        if other != kind:
            assert not engine[1][other]
    assert state['record'].exists()
    assert state['record'].stat().st_mode & 0o077 == 0
    assert 'SECRET_FAILURE_SENTINEL' not in capsys.readouterr().err
    assert set(yaml.safe_load(state['record'].read_text())) == {'version', 'project', 'resources'}


def test_recorded_ids_are_attempted_after_discovery_failure(state, engine):
    state['resources']['container'] = [IDS['container']]
    engine[2][('container', 'ls')] = True
    lab.cleanup(state)
    assert any(operation == 'ls' and '--filter' not in args for kind, operation, args in engine[0]
               if kind == 'container')
    assert not engine[1]['network'] and not engine[1]['image']


@pytest.mark.parametrize('fault,value', [('owner', 'production'), ('internal', False)])
def test_cleanup_rejects_foreign_labels_and_shared_network(state, engine, fault, value):
    engine[2][fault] = value
    assert lab.cleanup(state)
    assert IDS['network'] in engine[1]['network']
    if fault == 'owner':
        assert all(not (operation == 'rm') for _, operation, _ in engine[0])


def test_recovery_rechecks_saved_identity_labels_and_handles_partial_startup(state, engine):
    engine[1]['image'].clear()
    lab.recover(state['record'])
    assert not state['record'].exists()
    assert all(not identities for identities in engine[1].values())


def test_recovery_rejects_unowned_saved_id_even_when_discovery_finds_none(state, engine):
    state['resources']['container'] = [IDS['container']]
    lab.save_record(state)
    engine[2]['owner'] = 'production'
    with pytest.raises(RuntimeError, match='incomplete'):
        lab.recover(state['record'])
    assert state['record'].exists()
    assert engine[1]['container'] == {IDS['container']}


@pytest.mark.parametrize('project', ['production', 'degiro-c13-abc', 'degiro-c13-' + 'a' * 11, None])
def test_project_scope_is_strict(project):
    with pytest.raises(RuntimeError):
        lab.validate_project(project)


def test_recovery_rejects_public_record_before_docker(state, monkeypatch):
    state['record'].chmod(0o644)
    monkeypatch.setattr(lab, 'docker', lambda *args: pytest.fail('Docker before record validation'))
    with pytest.raises(RuntimeError, match='private'):
        lab.recover(state['record'])


def test_process_timeout_escalates_and_still_closes_pipes():
    process = subprocess.Popen([sys.executable, '-c',
        'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline() == b'ready\n'
        # Inject timeout at the wait boundary while retaining real kill/reap.
        original = process.wait
        waits = []

        def wait(timeout):
            waits.append(timeout)
            if len(waits) == 1:
                raise subprocess.TimeoutExpired('private-process', timeout)
            return original(timeout=timeout)

        process.wait = wait
        lab.stop_process(process)
        assert process.poll() is not None and waits == [10, 10]
        assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_process_failure_does_not_skip_docker_cleanup(state, engine, monkeypatch):
    state['processes'] = [object(), object()]
    attempts = []

    def fail(process):
        attempts.append(process)
        raise RuntimeError('private')

    monkeypatch.setattr(lab, 'stop_process', fail)
    assert lab.cleanup(state) == ['process', 'process']
    assert len(attempts) == 2 and all(not ids for ids in engine[1].values())
    assert state['record'].exists()


def test_lifecycle_preserves_primary_failure_and_private_record(state, engine, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lab, '__file__', str(tmp_path / 'scripts' / 'lab_cleanup.py'))
    engine[2][('container', 'rm')] = True

    def operation(directory, owned):
        assert directory.exists() and owned['record'].exists()
        (directory / 'compose.yaml').write_text('SECRET_MANIFEST_SENTINEL')
        raise ValueError('original failure')

    with pytest.raises(ValueError, match='original failure'):
        lab.execute(PROJECT, operation)
    records = list((tmp_path / 'tmp' / 'lab-recovery').glob('*.yaml'))
    assert len(records) == 1 and 'SECRET' not in records[0].read_text()
    assert 'SECRET' not in capsys.readouterr().err
    assert signal.getsignal(signal.SIGTERM) != lab.terminated


def test_successful_operation_reports_cleanup_failure(state, engine, monkeypatch, tmp_path):
    monkeypatch.setattr(lab, '__file__', str(tmp_path / 'scripts' / 'lab_cleanup.py'))
    engine[2][('network', 'rm')] = True
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        lab.execute(PROJECT, lambda directory, owned: None)


def test_catchable_sigterm_runs_same_lifecycle_and_restores_handler(tmp_path):
    program = '''
import os, signal, sys
from pathlib import Path
from scripts import lab_cleanup as lab
lab.__file__ = str(Path(sys.argv[1]) / 'scripts/lab_cleanup.py')
lab.docker = lambda *args: ''
previous = signal.getsignal(signal.SIGTERM)
def operation(directory, state):
    assert state['record'].exists()
    os.kill(os.getpid(), signal.SIGTERM)
try:
    lab.execute('degiro-c13-aaaaaaaaaa', operation)
except SystemExit as error:
    assert error.code == 143
else:
    raise SystemExit('SIGTERM ignored')
assert signal.getsignal(signal.SIGTERM) == previous
assert not list((Path(sys.argv[1]) / 'tmp/lab-recovery').glob('*.yaml'))
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize('location', ['handler-exit', 'cleanup-entry', 'ordinary-failure'])
def test_second_signal_cannot_interrupt_cleanup_transition(tmp_path, location):
    program = '''
import os, signal, sys
from pathlib import Path
from scripts import lab_cleanup as lab
lab.__file__ = str(Path(sys.argv[1]) / 'scripts/lab_cleanup.py')
lab.docker = lambda *args: ''
signals = {signal.SIGTERM, signal.SIGINT}
previous = {signum: signal.getsignal(signum) for signum in signals}
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
original_terminated = lab.terminated
original_signal = signal.signal
injected = []
def terminated(signum, frame):
    try:
        original_terminated(signum, frame)
    finally:
        if sys.argv[2] == 'handler-exit' and signum == signal.SIGTERM:
            injected.append('handler-exit')
            os.kill(os.getpid(), signal.SIGINT)
def install(signum, handler):
    if sys.argv[2] in ('cleanup-entry', 'ordinary-failure') and handler == signal.SIG_IGN and not injected:
        injected.append(sys.argv[2])
        os.kill(os.getpid(), signal.SIGINT)
    return original_signal(signum, handler)
lab.terminated = terminated
signal.signal = install
def operation(directory, state):
    assert state['record'].exists()
    if sys.argv[2] == 'ordinary-failure':
        raise ValueError('synthetic primary failure')
    os.kill(os.getpid(), signal.SIGTERM)
try:
    lab.execute('degiro-c13-aaaaaaaaaa', operation)
except SystemExit as error:
    assert sys.argv[2] != 'ordinary-failure'
    assert error.code == 143, error.code
except ValueError as error:
    assert sys.argv[2] == 'ordinary-failure'
    assert str(error) == 'synthetic primary failure'
else:
    raise AssertionError('First SIGTERM was ignored')
assert injected == [sys.argv[2]]
assert not list((Path(sys.argv[1]) / 'tmp/lab-recovery').glob('*.yaml'))
assert {signum: signal.getsignal(signum) for signum in signals} == previous
assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == mask
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path), location],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


def test_exact_id_mismatch_blocks_deletion(state, monkeypatch):
    calls = []
    def docker(kind, operation, *args):
        calls.append(operation)
        if operation == 'ls':
            return IDS['container']
        return json.dumps([{'Id': 'f' * 64, 'Config': {'Labels': {lab.LABEL: PROJECT}}}])
    monkeypatch.setattr(lab, 'docker', docker)
    with pytest.raises(RuntimeError, match='Foreign'):
        lab.remove_owned(state, 'container', IDS['container'])
    assert 'rm' not in calls


def test_unexpected_cleanup_error_never_masks_primary_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, '__file__', str(tmp_path / 'scripts/lab_cleanup.py'))
    monkeypatch.setattr(lab, 'cleanup', lambda state: (_ for _ in ()).throw(OSError('private')))
    def fail(directory, state):
        raise ValueError('primary')
    with pytest.raises(ValueError, match='primary'):
        lab.execute(PROJECT, fail)
    assert list((tmp_path / 'tmp/lab-recovery').glob('*.yaml'))


@pytest.mark.parametrize('script,entry', [('isolated_acceptance', 'acceptance'),
                                         ('check_interest_contract', 'interest')])
def test_both_controllers_protect_partial_startup_with_same_lifecycle(monkeypatch, tmp_path, script, entry):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    import importlib
    controller = importlib.import_module(script)
    calls = []
    def execute(project, operation):
        calls.append(project)
        operation(tmp_path, {'processes': []})
    def fail(*args):
        raise RuntimeError('partial startup')
    monkeypatch.setattr(controller.lab_cleanup, 'execute', execute)
    monkeypatch.setattr(controller, entry, fail)
    monkeypatch.setattr(sys, 'argv', ['controller', '--runtime-image', 'synthetic:runtime']
                        if script == 'isolated_acceptance' else ['controller'])
    with pytest.raises(RuntimeError, match='partial startup'):
        controller.main()
    assert len(calls) == 1
    lab.validate_project(calls[0])
