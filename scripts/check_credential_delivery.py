#!/usr/bin/env python3
"""Prove host-loader and container delivery using synthetic secrets only."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

import yaml

LOADER_SHA256 = 'f605a539aa0348cc82d161861d5630d381c23db52a513cb4bbc65bcebd8ecc51'
BROKER_KEYS = ('DEGIRO_USERNAME', 'DEGIRO_PASSWORD', 'DEGIRO_TOTP_SECRET')
SECRET_KEYS = (*BROKER_KEYS, 'GHOST_TOKEN')
LABEL = 'org.ghostfolio.degiro.credential-lab'
SIGNALS = {signal.SIGINT, signal.SIGTERM}


def ensure(condition):
    if not condition:
        raise RuntimeError('Synthetic credential delivery evidence failed')


def synthetic_values(generation):
    return {key: f'SYNTHETIC-{generation}-{key}-DO-NOT-LOG' for key in SECRET_KEYS}


def clean_environment():
    # Do not inherit operator credentials, proxy settings or dynamic-loader hooks.
    return {key: os.environ[key] for key in
            ('PATH', 'HOME', 'TMPDIR', 'XDG_RUNTIME_DIR')
            if key in os.environ}


def loader_fixture(loader, directory, generation=1, failure=None):
    """Execute the reviewed loader with every secret-bearing boundary substituted."""
    source = loader.read_bytes()
    ensure(hashlib.sha256(source).hexdigest() == LOADER_SHA256)
    body = synthetic_values(generation)
    store = directory / 'synthetic-encrypted-store'
    store.write_bytes(b'SYNTHETIC-ENCRYPTED-INPUT')
    store.chmod(0o600)
    if failure == 'missing':
        store.unlink()
    # Execute exactly the verified bytes, avoiding a second file read/race.
    module = {'__file__': str(loader), '__name__': 'synthetic_loader'}
    exec(compile(source, str(loader), 'exec'), module)
    module['main'].__globals__['STORE'] = store
    captured = []
    decrypted = '\n'.join(key + '=' + body[key] for key in BROKER_KEYS).encode()
    if failure == 'empty':
        decrypted = decrypted.replace(body[BROKER_KEYS[0]].encode(), b'')
    if failure == 'unexpected-key':
        decrypted += b'\nEXTRA=SYNTHETIC-EXTRA'

    def decrypt(command, **kwargs):
        ensure(command == ['docker', 'run', '--rm', '-i', '-u',
            str(os.getuid()) + ':' + str(os.getgid()), '-v',
            '/etc/komodo-secrets/age-agentvm.key:/k:ro', '-e', 'SOPS_AGE_KEY_FILE=/k',
            'ghcr.io/getsops/sops:v3.13.3', 'decrypt', '--input-type', 'dotenv',
            '--output-type', 'dotenv', '/dev/stdin'])
        ensure(kwargs == {'input': b'SYNTHETIC-ENCRYPTED-INPUT',
                         'capture_output': True, 'timeout': 60})
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 60, output=decrypted)
        return subprocess.CompletedProcess(command, 1 if failure == 'locked' else 0,
                                           decrypted, decrypted)

    read_bytes = Path.read_bytes

    def read_source(path):
        if path == store and failure == 'unreadable':
            raise OSError(body[BROKER_KEYS[0]])
        return read_bytes(path)

    def child(file, command, environment):
        ensure(file == 'synthetic-child' and command == ['synthetic-child'])
        captured.append(environment.copy())

    output = io.StringIO()
    inherited = {**clean_environment(), 'GHOST_TOKEN': body['GHOST_TOKEN']}
    # Existing stale broker values must never defeat unavailable-source failure.
    inherited.update({key: 'SYNTHETIC-STALE' for key in BROKER_KEYS})
    with patch.dict(os.environ, inherited, clear=True), \
            patch.object(sys, 'argv', [str(loader), 'synthetic-child']), \
            patch.object(subprocess, 'run', decrypt), patch.object(os, 'execvpe', child), \
            patch.object(Path, 'read_bytes', read_source), \
            redirect_stdout(output), redirect_stderr(output):
        status = module['main']()
    text = output.getvalue()
    ensure(not any(value in text for value in body.values()))
    if failure:
        ensure(status == 1 and not captured)
        ensure(text == 'DEGIRO credential loading failed; details suppressed.\n')
        return None
    ensure(status is None and len(captured) == 1 and not text)
    ensure(all(captured[0].get(key) == body[key] for key in SECRET_KEYS))
    return captured[0]


def docker(*arguments, environment=None, timeout=30):
    result = subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *arguments], capture_output=True, text=True,
                            env=environment or clean_environment(), timeout=timeout)
    if result.returncode:
        # Never echo Docker output/exception text: it can contain environment data.
        raise RuntimeError('Synthetic credential lab Docker operation failed')
    # Supercronic writes its job/output records to stderr.
    return result.stdout + result.stderr if arguments[0] == 'logs' else result.stdout


def create_arguments(image, name, project, probe, cron=False):
    args = ['create', '--name', name, '--label', LABEL + '=' + project,
            '--network=none', '--read-only', '--restart=no', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
            '--mount', f'type=bind,source={probe},target=/app/degiro_to_ghostfolio.py,readonly']
    for key in SECRET_KEYS:
        args.extend(['--env', key])
    args.extend(['--env', 'DRY_RUN=1'])
    if cron:
        args.extend(['--env', 'CRON=* * * * *'])
    return [*args, image]


def probe_source(values, generation):
    digests = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in values.items()}
    # Only hashes go into the probe mount; cleartext sentinels stay in memory.
    return f'''import hashlib, os, sys
assert sys.argv[1:] == ["--sync"]
assert os.getuid() == 10001
assert os.environ.get("DRY_RUN") == "1"
for key, expected in {digests!r}.items():
    assert hashlib.sha256(os.environ[key].encode()).hexdigest() == expected
print("PASS synthetic credential generation {generation}", flush=True)
'''


def save_record(path, project, resources):
    # An interrupted write must preserve the previous usable recovery record.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            pending.chmod(0o600)
            yaml.safe_dump({'project': project, 'containers': resources}, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(pending, path)
            # Persist the renamed entry too, not only the temporary file bytes.
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            pending.unlink(missing_ok=True)


def terminated(signum, frame):
    # Atomically block both catchable signals before leaving the operation.
    # A second signal must not interrupt the transition into bounded cleanup.
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    raise SystemExit(128 + signum)


def remove_owned(identity, name, project):
    # Read only identity/ownership, never serialize Docker Config.Env.
    matches = docker('container', 'ls', '-aq', '--no-trunc', '--filter', 'name=^/' + name + '$').split()
    if not matches:
        return
    ensure(len(matches) == 1 and (identity is None or matches[0] == identity))
    inspected = docker('inspect', '--format',
        '{{.Id}} {{.Name}} {{index .Config.Labels "' + LABEL + '"}}', matches[0]).strip()
    ensure(inspected == matches[0] + ' /' + name + ' ' + project)
    docker('container', 'rm', '-f', matches[0])


def check_container(image, directory, project, record, resources, environment, generation, cron):
    probe = directory / f'probe-{generation}-{int(cron)}.py'
    probe.write_text(probe_source(synthetic_values(generation), generation))
    probe.chmod(0o644)
    name = project + '-' + str(len(resources))
    resources[name] = None
    save_record(record, project, resources)
    identity = docker(*create_arguments(image, name, project, probe, cron), environment=environment).strip()
    ensure(re.fullmatch(r'[0-9a-f]{64}', identity) is not None)
    resources[name] = identity
    save_record(record, project, resources)
    marker = f'PASS synthetic credential generation {generation}'
    if not cron:
        output = docker('start', '-a', identity)
        ensure(marker in output)
    else:
        docker('start', identity)
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            output = docker('logs', identity)
            if marker in output:
                ensure('Running with validated cron schedule' in output)
                ensure(docker('inspect', '--format', '{{.State.Running}}', identity).strip() == 'true')
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Synthetic credential cron did not run in bounded window')
    ensure(not any(value in output for value in synthetic_values(generation).values()))
    remove_owned(identity, name, project)
    del resources[name]
    save_record(record, project, resources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader', required=True, type=Path)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    ensure(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_./:@-]*', args.image) is not None)
    project = 'degiro-credentials-' + uuid.uuid4().hex[:12]
    root = Path(__file__).resolve().parents[1] / 'tmp' / 'credential-recovery'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = root / (project + '.yaml')
    resources = {}
    save_record(record, project, resources)
    previous = {signum: signal.signal(signum, terminated) for signum in SIGNALS}
    try:
        with tempfile.TemporaryDirectory(prefix=project + '-') as temporary:
            directory = Path(temporary)
            # UID10001 must traverse the synthetic, hashes-only mount directory.
            directory.chmod(0o755)
            for failure in ('missing', 'locked', 'timeout', 'unreadable', 'empty', 'unexpected-key'):
                loader_fixture(args.loader, directory, failure=failure)
            print('PASS unavailable/invalid synthetic source never starts a child; private diagnostics', flush=True)
            for generation in (1, 2):
                environment = loader_fixture(args.loader, directory, generation)
                for cron in (False, True):
                    check_container(args.image, directory, project, record, resources,
                                    environment, generation, cron)
                print(f'PASS run-once and real cron generation {generation}; recreate reloads environment', flush=True)
    finally:
        primary = sys.exc_info()[1]
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
        failed = False
        try:
            for name, identity in list(resources.items()):
                try:
                    remove_owned(identity, name, project)
                    del resources[name]
                except Exception:
                    failed = True
            try:
                save_record(record, project, resources)
                if not failed:
                    record.unlink()
            except Exception:
                failed = True
            if failed:
                print('Synthetic credential cleanup incomplete; ownership record: ' + str(record), file=sys.stderr)
        finally:
            try:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        if failed and primary is None:
            raise RuntimeError('Synthetic credential lab cleanup incomplete')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Synthetic credential delivery check failed; details suppressed.', file=sys.stderr)
        sys.exit(1)
