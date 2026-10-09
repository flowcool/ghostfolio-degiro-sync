#!/usr/bin/env python3
"""Bounded cleanup and explicit recovery for UUID-owned synthetic Docker labs."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

import yaml

LABEL = 'com.docker.compose.project'
KINDS = ('container', 'network', 'image')


def validate_project(project):
    if not isinstance(project, str) or not re.fullmatch(
            r'degiro-(?:c13-[0-9a-f]{10}|interest-[0-9a-f]{12})', project):
        raise RuntimeError('Invalid owned lab project')


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Owned lab Docker operation failed')
    return result.stdout


def save_record(state):
    # Never serialize process objects, manifests, environment or authentication.
    body = {'version': 1, 'project': state['project'], 'resources': state['resources']}
    path = state['record']
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            os.chmod(pending, 0o600)
            yaml.safe_dump(body, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


def stop_process(process):
    try:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def discover(state, kind):
    flag = '-aq' if kind == 'container' else '-q'
    found = docker(kind, 'ls', flag, '--no-trunc', '--filter', 'label=' + LABEL + '=' + state['project'])
    identities = found.split()
    if any(not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', identity) for identity in identities):
        raise RuntimeError('Invalid owned Docker identity')
    state['resources'][kind] = sorted(set(state['resources'][kind] + identities))
    save_record(state)


def remove_owned(state, kind, identity):
    # Re-list exact IDs to distinguish already absent resources from inspect failure.
    present = docker(kind, 'ls', '-aq' if kind == 'container' else '-q', '--no-trunc').split()
    if identity not in present:
        return
    inspected = json.loads(docker(kind, 'inspect', identity))
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise RuntimeError('Invalid owned Docker inspection')
    info = inspected[0]
    labels = (info.get('Config') or {}).get('Labels') if kind != 'network' else info.get('Labels')
    if info.get('Id') != identity or not isinstance(labels, dict) or labels.get(LABEL) != state['project']:
        raise RuntimeError('Foreign Docker resource rejected')
    if kind == 'network' and info.get('Internal') is not True:
        raise RuntimeError('Shared Docker network rejected')
    if kind == 'container':
        docker(kind, 'rm', '-f', identity)
    else:
        # Never force removal of an image used by another container.
        docker(kind, 'rm', identity)


def cleanup(state):
    failures = []
    for process in state['processes']:
        try:
            stop_process(process)
        except Exception:
            failures.append('process')
    for kind in KINDS:
        try:
            discover(state, kind)
        except Exception:
            failures.append(kind + '-discovery')
        # Even a failed discovery must not prevent recorded-ID cleanup or other kinds.
        for identity in state['resources'][kind]:
            try:
                remove_owned(state, kind, identity)
            except Exception:
                failures.append(kind + '-removal')
    if not failures:
        try:
            state['record'].unlink(missing_ok=True)
        except OSError:
            failures.append('record-removal')
    if not failures:
        print('Owned lab containers/network/images removed', flush=True)
    else:
        print('Owned lab cleanup incomplete; retain recovery record: ' + str(state['record']),
              file=sys.stderr, flush=True)
    return failures


def terminated(signum, frame):
    raise SystemExit(128 + signum)


def execute(project, operation):
    validate_project(project)
    root = Path(__file__).resolve().parents[1] / 'tmp' / 'lab-recovery'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    record = root / (project + '.yaml')
    # Unique project records cannot overwrite unresolved ownership evidence.
    with record.open('x'):
        record.chmod(0o600)
    state = {'project': project, 'record': record,
             'resources': {kind: [] for kind in KINDS}, 'processes': []}
    save_record(state)
    previous = {signum: signal.signal(signum, terminated)
                for signum in (signal.SIGTERM, signal.SIGINT)}
    primary = None
    try:
        with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
            operation(Path(directory), state)
    except BaseException as error:
        primary = error
        raise
    finally:
        # A repeated catchable signal must not interrupt bounded recovery.
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            try:
                failures = cleanup(state)
            except Exception:
                failures = ['cleanup']
                print('Owned lab cleanup incomplete; retain recovery record: ' + str(record),
                      file=sys.stderr, flush=True)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if failures and primary is None:
            raise RuntimeError('Owned lab cleanup incomplete; see recovery record')


def recover(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise RuntimeError('Owned recovery record must be private and operator-owned')
    body = yaml.safe_load(path.read_text())
    if not isinstance(body, dict) or set(body) != {'version', 'project', 'resources'} or body['version'] != 1:
        raise RuntimeError('Invalid owned recovery record')
    validate_project(body['project'])
    resources = body['resources']
    if not isinstance(resources, dict) or set(resources) != set(KINDS):
        raise RuntimeError('Invalid owned recovery resources')
    for identities in resources.values():
        if not isinstance(identities, list) or any(not isinstance(identity, str) or
                not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', identity) for identity in identities):
            raise RuntimeError('Invalid owned recovery identity')
    state = {**body, 'record': path, 'processes': []}
    if cleanup(state):
        raise RuntimeError('Owned lab recovery incomplete; record retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', required=True, help='Private nonsecret owned-lab record')
    recover(parser.parse_args().recover)
