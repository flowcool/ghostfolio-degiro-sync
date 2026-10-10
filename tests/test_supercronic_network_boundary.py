"""Managed cron must not enable the Go HTTP client through inherited Sentry."""

import json
import os
from pathlib import Path
import subprocess
import sys


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
