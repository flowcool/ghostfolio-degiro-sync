"""Managed cron must not enable the Go HTTP client through inherited Sentry."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_managed_cron_clears_sentry_before_validation_and_execution(tmp_path):
    fake = tmp_path / 'supercronic'
    log = tmp_path / 'calls.jsonl'
    fake.write_text('#!' + sys.executable + '\n'
        'import json, os, sys\n'
        'keys = [key for key in ("SENTRY_DSN", "SENTRY_ENVIRONMENT", "SENTRY_RELEASE") if key in os.environ]\n'
        'with open(os.environ["TEST_SUPERCRONIC_LOG"], "a") as stream:\n'
        ' stream.write(json.dumps({"args": sys.argv[1:], "sentry_keys": keys}) + "\\n")\n'
        'sys.exit(1 if keys else 0)\n', encoding='utf-8')
    fake.chmod(0o700)
    environment = dict(os.environ, PATH=str(tmp_path) + ':' + os.environ['PATH'],
        CRON='* * * * *', SENTRY_DSN='https://synthetic.invalid/1',
        SENTRY_ENVIRONMENT='synthetic', SENTRY_RELEASE='synthetic',
        TEST_SUPERCRONIC_LOG=str(log), TMPDIR=str(tmp_path))
    script = Path(__file__).resolve().parents[1] / 'entrypoint.sh'
    result = subprocess.run(['bash', str(script)], env=environment, capture_output=True,
        text=True, timeout=5, check=False)
    assert result.returncode == 0
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert len(calls) == 2
    assert calls[0]['args'][0] == '-test'
    assert calls[1]['args'] == [calls[0]['args'][1]]
    assert all(call['sentry_keys'] == [] for call in calls)
    assert all('-prometheus-listen-address' not in call['args'] for call in calls)


@pytest.mark.parametrize('arguments,version,revision,expected_version,expected_commit', [
    ([], '1.2.3', '0123456789abcdef0123456789abcdef01234567', '1.2.3', '0123456789ab'),
    (['--sync'], '1.2.3', '0123456789abcdef0123456789abcdef01234567', '1.2.3', '0123456789ab'),
    (['--help'], '', '', 'dev', 'unknown'),
    (['--sync'], 'invalid\ninjected', 'invalid\ninjected', 'dev', 'unknown'),
])
def test_connector_entrypoint_reports_safe_identity_and_preserves_exit(
        tmp_path, arguments, version, revision, expected_version, expected_commit):
    fake = tmp_path / 'python'
    log = tmp_path / 'arguments.json'
    fake.write_text('#!' + sys.executable + '\n'
        'import json,os,sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["TEST_ARGUMENTS"]).write_text(json.dumps(sys.argv[1:]))\n'
        'raise SystemExit(17)\n')
    fake.chmod(0o700)
    environment = {'PATH': str(tmp_path) + ':' + os.defpath, 'TEST_ARGUMENTS': str(log),
        'APP_VERSION': version, 'APP_REVISION': revision}
    script = Path(__file__).resolve().parents[1] / 'entrypoint.sh'
    result = subprocess.run(['bash', str(script), *arguments], env=environment,
        capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 17 and result.stderr == ''
    assert result.stdout.count('DEGIRO SYNC') == 1
    assert result.stdout.count(f'ghostfolio-degiro-sync version {expected_version} — commit {expected_commit}') == 1
    assert 'injected' not in result.stdout
    assert json.loads(log.read_text()) == ['-m', 'ghostfolio_degiro_sync', *(arguments or ['--sync'])]


def test_notification_worker_entrypoint_is_silent_before_execution(tmp_path):
    fake = tmp_path / 'python'
    fake.write_text('#!/bin/sh\nexit 10\n')
    fake.chmod(0o700)
    script = Path(__file__).resolve().parents[1] / 'entrypoint.sh'
    result = subprocess.run(['bash', str(script), '--notify-worker'],
        env={'PATH': str(tmp_path) + ':' + os.defpath}, capture_output=True, text=True, timeout=5)
    assert result.returncode == 10 and result.stdout == '' and result.stderr == ''


def test_arbitrary_entrypoint_command_retains_output_and_exit_status():
    script = Path(__file__).resolve().parents[1] / 'entrypoint.sh'
    result = subprocess.run(['bash', str(script), 'bash', '-c', 'printf arbitrary; exit 7'],
        env={'PATH': os.defpath}, capture_output=True, text=True, timeout=5)
    assert result.returncode == 7 and result.stdout == 'arbitrary' and result.stderr == ''
