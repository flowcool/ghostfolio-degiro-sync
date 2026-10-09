import importlib.util
from pathlib import Path
import signal
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location('delivery',
    Path(__file__).resolve().parents[1] / 'scripts/check_credential_delivery.py')
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)


def test_only_environment_names_enter_container_arguments(tmp_path):
    args = delivery.create_arguments('synthetic-image', 'synthetic-name', 'synthetic-project',
                                     tmp_path / 'probe.py', cron=True)
    keys = [args[index + 1] for index, value in enumerate(args) if value == '--env']
    assert keys == [*delivery.SECRET_KEYS, 'DRY_RUN=1', 'CRON=* * * * *']
    assert not any(value in ' '.join(args) for value in delivery.synthetic_values(1).values())
    assert '--network=none' in args and '--restart=no' in args
    assert '--read-only' in args and '--cap-drop=ALL' in args
    assert '--security-opt=no-new-privileges' in args
    assert args[args.index('--tmpfs') + 1] == '/tmp:rw,nosuid,nodev,size=16m'
    assert 'readonly' in args[args.index('--mount') + 1]


def test_operator_secrets_and_code_injection_environment_are_not_inherited(monkeypatch):
    for key in (*delivery.SECRET_KEYS, 'HTTP_PROXY', 'LD_PRELOAD', 'PYTHONPATH', 'DOCKER_HOST', 'DOCKER_CONTEXT'):
        monkeypatch.setenv(key, 'PRIVATE-SENTINEL')
    assert set(delivery.clean_environment()).isdisjoint(
        {*delivery.SECRET_KEYS, 'HTTP_PROXY', 'LD_PRELOAD', 'PYTHONPATH', 'DOCKER_HOST', 'DOCKER_CONTEXT'})


def test_probe_mount_contains_hashes_and_never_plaintext():
    values = delivery.synthetic_values(2)
    source = delivery.probe_source(values, 2)
    assert not any(value in source for value in values.values())
    assert 'os.getuid() == 10001' in source
    assert 'PASS synthetic credential generation 2' in source


def test_changed_loader_is_rejected_before_executing_it(tmp_path):
    loader = tmp_path / 'loader.py'
    marker = tmp_path / 'executed'
    loader.write_text(f'open({str(marker)!r}, "w").write("unsafe")')
    with pytest.raises(RuntimeError, match='evidence failed'):
        delivery.loader_fixture(loader, tmp_path)
    assert not marker.exists()


@pytest.mark.parametrize('identity,label,name', [
    ('a' * 64, 'ours', '/wrong'),
    ('a' * 64, 'foreign', '/ours'),
    ('b' * 64, 'ours', '/ours'),
])
def test_foreign_container_is_never_removed(monkeypatch, identity, label, name):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[1] == 'ls':
            return identity + '\n'
        return identity + ' ' + name + ' ' + label + '\n'

    monkeypatch.setattr(delivery, 'docker', docker)
    with pytest.raises(RuntimeError):
        delivery.remove_owned('a' * 64, 'ours', 'ours')
    assert not any('rm' in args for args in calls)


def test_cleanup_rechecks_identity_and_label_without_inspecting_environment(monkeypatch):
    calls = []
    identity = 'a' * 64

    def docker(*args, **kwargs):
        calls.append(args)
        if args[1] == 'ls':
            return identity + '\n'
        if args[0] == 'inspect':
            return identity + ' /ours project\n'
        return ''

    monkeypatch.setattr(delivery, 'docker', docker)
    delivery.remove_owned(identity, 'ours', 'project')
    assert calls[-1] == ('container', 'rm', '-f', identity)
    assert not any('.Config.Env' in str(args) for args in calls)


def test_docker_failures_do_not_echo_private_output(monkeypatch):
    def run(*args, **kwargs):
        assert set(kwargs['env']).isdisjoint(delivery.SECRET_KEYS)
        assert args[0][1] == '--host=unix:///var/run/docker.sock'
        assert kwargs['timeout'] == 30
        return subprocess.CompletedProcess(args[0], 1, 'PRIVATE-STDOUT', 'PRIVATE-STDERR')

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(RuntimeError) as error:
        delivery.docker('create', 'synthetic-image')
    assert 'PRIVATE' not in str(error.value)


def test_cron_evidence_in_docker_stderr_is_not_lost(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
        subprocess.CompletedProcess(args[0], 0, '', 'PASS synthetic cron output'))
    assert delivery.docker('logs', 'synthetic-container') == 'PASS synthetic cron output'


def test_ownership_record_is_private_nonsecret_yaml(tmp_path):
    path = tmp_path / 'ownership.yaml'
    delivery.save_record(path, 'ours', {'container-name': 'a' * 64})
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'containers:' in path.read_text()
    assert all(key not in path.read_text() for key in delivery.SECRET_KEYS)


@pytest.mark.parametrize('failure', ['write', 'replace'])
def test_interrupted_record_update_keeps_prior_private_record(tmp_path, monkeypatch, failure):
    path = tmp_path / 'ownership.yaml'
    delivery.save_record(path, 'ours', {'old': 'a' * 64})
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError('synthetic record failure')

    monkeypatch.setattr(delivery.yaml if failure == 'write' else delivery.os,
                        'safe_dump' if failure == 'write' else 'replace', fail)
    with pytest.raises(OSError):
        delivery.save_record(path, 'ours', {'new': 'b' * 64})
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('failure', [None, 'missing', 'locked', 'timeout',
                                    'unreadable', 'empty', 'unexpected-key'])
def test_pinned_loader_boundaries_are_offline_and_fail_before_child(tmp_path, failure):
    loader = Path(__file__).parent / 'fixtures/runtime_env_loader.py'
    result = delivery.loader_fixture(loader, tmp_path, generation=2, failure=failure)
    if failure:
        assert result is None
    else:
        assert all(result[key] == value for key, value in delivery.synthetic_values(2).items())


def test_termination_blocks_both_signals_before_cleanup_transition(monkeypatch):
    calls = []
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: calls.append(args))
    with pytest.raises(SystemExit) as error:
        delivery.terminated(signal.SIGTERM, None)
    assert error.value.code == 128 + signal.SIGTERM
    assert calls == [(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})]


@pytest.mark.parametrize('failure', [None, 'save', 'unlink', 'remove'])
@pytest.mark.parametrize('primary_failure', [False, True])
def test_main_finalization_restores_signal_state_and_preserves_primary_error(
        tmp_path, monkeypatch, capsys, failure, primary_failure):
    import sys
    import yaml

    monkeypatch.setattr(delivery, '__file__', str(tmp_path / 'scripts/check.py'))
    monkeypatch.setattr(sys, 'argv', ['check.py', '--loader', 'synthetic', '--image', 'synthetic'])
    monkeypatch.setattr(delivery, 'loader_fixture', lambda *args, **kwargs: {})
    real_save, real_unlink = delivery.save_record, Path.unlink
    saves = []

    def save(record, project, resources):
        saves.append(record)
        if failure == 'save' and len(saves) == 3:
            raise OSError('PRIVATE-FAILURE-SENTINEL')
        real_save(record, project, resources)

    def check(image, directory, project, record, resources, *args):
        if not resources:
            resources['synthetic-container'] = 'a' * 64
            save(record, project, resources)
        if primary_failure:
            raise ValueError('primary operation failed')

    def remove(*args):
        if failure == 'remove':
            raise OSError('PRIVATE-FAILURE-SENTINEL')

    def unlink(path, *args, **kwargs):
        if failure == 'unlink' and path.suffix == '.yaml':
            raise OSError('PRIVATE-FAILURE-SENTINEL')
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(delivery, 'save_record', save)
    monkeypatch.setattr(delivery, 'check_container', check)
    monkeypatch.setattr(delivery, 'remove_owned', remove)
    monkeypatch.setattr(Path, 'unlink', unlink)
    handlers = {signum: signal.getsignal(signum) for signum in delivery.SIGNALS}
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    try:
        if primary_failure:
            with pytest.raises(ValueError, match='primary operation failed'):
                delivery.main()
        elif failure:
            with pytest.raises(RuntimeError, match='lab cleanup incomplete'):
                delivery.main()
        else:
            delivery.main()
        assert {signum: signal.getsignal(signum) for signum in handlers} == handlers
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == mask
    finally:
        # Keep a failing regression from contaminating the runner's signal state.
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    output = capsys.readouterr()
    assert 'PRIVATE-FAILURE-SENTINEL' not in output.out + output.err
    record = saves[0]
    if failure:
        assert str(record) in output.err
        assert record.exists() and record.stat().st_mode & 0o777 == 0o600
        body = yaml.safe_load(record.read_text())
        assert body['containers'] == ({'synthetic-container': 'a' * 64}
                                      if failure in ('save', 'remove') else {})
    else:
        assert not record.exists() and output.err == ''
