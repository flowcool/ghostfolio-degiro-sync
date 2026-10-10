#!/usr/bin/env python3
"""Verify the infra-owned isolated stack before invoking its bounded lab runner."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT = 'ghostfolio-degiro-lab'
MARKER = 'persistent-v1'


def command(args, timeout=30, environment=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
        env=environment, check=False)
    if result.returncode or len(result.stdout) > 2_000_000:
        raise RuntimeError('Lab command failed; private details suppressed')
    return result.stdout


def verify_stack(compose):
    identity = command(compose + ['ps', '-q', 'ghostfolio']).strip()
    if not identity or '\n' in identity:
        raise RuntimeError('Exactly one running lab Ghostfolio is required')
    # Select nonsecret fields: never inspect or print Config.Env.
    fields = '{{json .Config.Labels}}\n{{json .NetworkSettings.Networks}}\n{{json .HostConfig.PortBindings}}\n{{json .State.Running}}\n{{json .Image}}'
    labels, networks, ports, running, image = [json.loads(line) for line in
        command(['docker', 'inspect', '--format', fields, identity]).splitlines()]
    if (labels.get('com.docker.compose.project') != PROJECT
            or labels.get('com.docker.compose.service') != 'ghostfolio'
            or labels.get('io.flowcool.degiro-lab') != MARKER or running is not True
            or len(networks) != 1 or set(ports) != {'3333/tcp'}
            or not ports['3333/tcp']
            or any(binding['HostIp'] != '127.0.0.1'
                for bindings in ports.values() for binding in (bindings or []))):
        raise RuntimeError('Lab server ownership, network or localhost boundary differs')
    image_labels = json.loads(command(['docker', 'image', 'inspect', '--format',
        '{{json .Config.Labels}}', image]))
    if image_labels.get('io.flowcool.degiro-lab') != MARKER:
        raise RuntimeError('Native lab fixture image marker missing')
    network = next(iter(networks))
    fields = '{{json .Internal}}\n{{json .Labels}}\n{{json .Containers}}'
    internal, labels, members = [json.loads(line) for line in
        command(['docker', 'network', 'inspect', '--format', fields, network]).splitlines()]
    if (internal is not True or identity not in members or labels.get('com.docker.compose.project') != PROJECT
            or labels.get('com.docker.compose.network') != 'lab'):
        raise RuntimeError('Lab network must be internal and owned by the lab project')
    for member in members:
        owner = command(['docker', 'inspect', '--format',
            '{{index .Config.Labels "com.docker.compose.project"}}', member]).strip()
        if owner != PROJECT:
            raise RuntimeError('Foreign container attached to the lab network')
    return network


def invoke(args):
    path = Path(args.compose_file).resolve()
    compose = ['docker', 'compose', '-p', PROJECT, '-f', str(path)]
    network = verify_stack(compose)
    # Do not allow a replacement Compose runner to inherit broker credentials.
    # The checked-in lab definition contains no broker variables or external network.
    rendered = json.loads(command(compose + ['--profile', 'tests', 'config', '--format', 'json']))
    service = rendered['services']['lab-check']
    if (set(service['networks']) != {'lab'} or service.get('privileged')
            or service.get('user') != '10001:10001' or service.get('read_only') is not True
            or set(service.get('environment', {})) != {'DEGIRO_PERSISTENT_LAB'}
            or service.get('entrypoint') is not None or service.get('extra_hosts')
            or any(service.get(key) for key in ('network_mode', 'devices', 'volumes_from', 'links', 'ports', 'pid', 'ipc'))
            or service.get('cap_add') or set(service.get('cap_drop', [])) != {'ALL'}
            or not any(value in ('no-new-privileges:true', 'no-new-privileges')
                for value in service.get('security_opt', []))
            or rendered['networks']['lab'].get('name') != network
            or rendered['networks']['lab'].get('internal') is not True):
        raise RuntimeError('Lab runner isolation differs')
    mounts = service.get('volumes', [])
    if len(mounts) != 4 or {mount['target'] for mount in mounts} != {'/lab/persistent_lab.py', '/lab/fixture.yaml', '/captures', '/runs'}:
        raise RuntimeError('Missing or unexpected lab runner mount')
    for mount in mounts:
        if (mount.get('type') != 'bind' or mount.get('bind', {}).get('create_host_path') is not False
                or (mount['target'] != '/runs' and mount.get('read_only') is not True)):
            raise RuntimeError('Lab runner mount permissions differ')
    environment = dict(os.environ, DEGIRO_PERSISTENT_LAB=MARKER)
    command(compose + ['run', '--rm', '--no-deps', '-T',
        '-e', 'DEGIRO_PERSISTENT_LAB', 'lab-check', 'python', '/lab/persistent_lab.py',
        args.scenario, '--manifest-sha256', args.manifest_sha256], timeout=600,
        environment=environment)
    print('PASS isolated persistent lab ' + args.scenario + '; private evidence retained in runs directory')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=('synthetic', 'replay'))
    parser.add_argument('--compose-file', default='compose.lab.yaml')
    parser.add_argument('--manifest-sha256', required=True)
    try:
        invoke(parser.parse_args())
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Persistent lab run refused; private details suppressed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
