"""Health probes use synthetic status and one disposable owned local process."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts import check_scheduler as health


@pytest.mark.parametrize('cron', ['', '  '])
def test_run_once_needs_no_process_status(tmp_path, cron):
    health.check_scheduler(cron, tmp_path / 'missing')


@pytest.mark.parametrize('status', ['', 'Name: supercronic\n',
    'Name: python\nState: S (sleeping)\n', 'Name: supercronic\nState: T (stopped)\n',
    'Name: supercronic\nState: Z (zombie)\n', 'Name: supercronic\nState: ?\n'])
def test_invalid_or_stopped_scheduler_refuses(tmp_path, status):
    path = tmp_path / 'status'
    path.write_text(status)
    with pytest.raises(RuntimeError, match='Scheduler process'):
        health.check_scheduler('* * * * *', path)


def test_health_cli_failure_is_private(monkeypatch, capsys):
    monkeypatch.setenv('CRON', '* * * * *')
    def unavailable(*args):
        raise RuntimeError('SYNTHETIC-PRIVATE-SENTINEL')
    monkeypatch.setattr(health, 'check_scheduler', unavailable)
    assert health.main() == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert output.err == 'Scheduler healthcheck failed\n'


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux proc status contract')
def test_owned_live_process_suspend_and_exit_are_detected():
    code = ('import ctypes, time\n'
            'libc = ctypes.CDLL(None)\n'
            'assert libc.prctl(15, b"supercronic", 0, 0, 0) == 0\n'
            'print("READY", flush=True)\n'
            'time.sleep(10)\n')
    process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    status = Path('/proc') / str(process.pid) / 'status'
    try:
        import select
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline() == 'READY\n'
        health.check_scheduler('* * * * *', status)
        os.kill(process.pid, signal.SIGSTOP)
        deadline = time.monotonic() + 2
        while 'State:\tT' not in status.read_text():
            if time.monotonic() >= deadline:
                raise RuntimeError('Owned synthetic process did not stop')
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match='stopped'):
            health.check_scheduler('* * * * *', status)
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGCONT)
            process.terminate()
        process.communicate(timeout=5)
    with pytest.raises(RuntimeError, match='unavailable'):
        health.check_scheduler('* * * * *', status)
