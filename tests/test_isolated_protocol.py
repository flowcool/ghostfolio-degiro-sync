"""Offline process boundaries for the disposable lab controller."""
import subprocess
import sys

import pytest

from scripts.isolated_acceptance import acquire_barrier, compose_command, driver_lines


@pytest.mark.parametrize('program,expected', [
    ('print("ARM_BARRIER: cash"); print("QUIESCENCE_READY: cash")',
     ['ARM_BARRIER: cash', 'QUIESCENCE_READY: cash']),
    ('import os; os.write(1,b"ARM_"); os.write(1,b"BARRIER: cash\\n")',
     ['ARM_BARRIER: cash']),
])
def test_driver_protocol_preserves_complete_ordered_lines(program, expected):
    with subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE) as process:
        assert list(driver_lines(process, timeout=5)) == expected
        assert process.wait(timeout=5) == 0


@pytest.mark.parametrize('program,message', [
    ('import time; time.sleep(10)', 'deadline'),
    ('import os; os.write(1,b"unfinished")', 'Incomplete'),
    ('print("x"*9000)', 'line budget'),
])
def test_driver_protocol_failure_is_bounded(program, message):
    process = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE)
    try:
        with pytest.raises(RuntimeError, match=message):
            list(driver_lines(process, timeout=.2 if message == 'deadline' else 5))
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def test_acceptance_compose_project_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'unowned-production')
    assert compose_command('owned-uuid', tmp_path / 'compose.yaml') == [
        'docker', 'compose', '-p', 'owned-uuid', '-f', str(tmp_path / 'compose.yaml')]


def test_optimized_acceptance_refuses_before_docker_or_argument_handling():
    program = '''
import scripts.isolated_acceptance as lab
lab.run = lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit('Docker called'))
try:
    lab.main()
except RuntimeError as error:
    if str(error) != 'Owned acceptance requires Python assertions enabled':
        raise
else:
    raise SystemExit('Optimized harness accepted')
'''
    result = subprocess.run([sys.executable, '-O', '-c', program],
        capture_output=True, timeout=10)
    assert result.returncode == 0


def test_barrier_preserves_split_identity_and_acknowledgement():
    program = '''
import os, sys
assert sys.stdin.readline() == 'SELECT pg_backend_pid();\\n'
assert sys.stdin.readline() == 'SELECT pg_advisory_lock(81005611);\\n'
os.write(1, b'12')
os.write(1, b'3\\n\\n')
sys.stdin.read()
'''
    process, identity = acquire_barrier([sys.executable, '-c', program], timeout=5)
    try:
        assert identity == 123
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.parametrize('output,hang,message', [
    (b'', True, 'deadline'),
    (b'123', True, 'deadline'),
    (b'123\n', True, 'deadline'),
    (b'123\n', False, 'Incomplete'),
    (b'sensitive-sentinel\n\n', False, 'identity'),
    (b'0\n\n', False, 'identity'),
    (b'2147483648\n\n', False, 'identity'),
    (b'123\nsensitive-sentinel\n', False, 'acknowledgement'),
    (b'\xff\n\n', False, 'Incomplete'),
    (b'x' * 9000, False, 'line budget'),
])
def test_barrier_failures_are_bounded_private_and_reap_process(monkeypatch, output, hang, message):
    created = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr('scripts.isolated_acceptance.subprocess.Popen', start)
    program = ('import os, sys, time; sys.stdin.readline(); sys.stdin.readline(); '
        f'os.write(1, {output!r}); ' + ('time.sleep(10)' if hang else ''))
    with pytest.raises(RuntimeError, match=message) as failure:
        acquire_barrier([sys.executable, '-c', program], timeout=.2 if hang else 5)
    assert 'sensitive-sentinel' not in str(failure.value)
    assert len(created) == 1 and created[0].poll() is not None
    assert all(stream.closed for stream in
        (created[0].stdin, created[0].stdout, created[0].stderr))
