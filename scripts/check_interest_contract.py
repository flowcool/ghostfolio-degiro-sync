#!/usr/bin/env python3
"""Characterize synthetic INTEREST in an owned disposable Ghostfolio instance."""
import json
from pathlib import Path
import secrets
import sys
import time
import uuid

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ghostfolio_core as core
import lab_cleanup
from isolated_acceptance import GHOST_IMAGE, POSTGRES_IMAGE, REDIS_IMAGE, run


def ensure(condition):
    if not condition:
        raise RuntimeError('Owned interest probe evidence or isolation check failed')


def compose_command(project, path):
    return ['docker', 'compose', '-p', project, '-f', str(path)]


def verify_stored(activities, body):
    ensure(type(body.get('count')) is int and body['count'] == len(activities))
    accepted = core.accepted_import_subset(activities, body)
    ensure(sorted(accepted, key=lambda row: row['comment']) ==
           sorted(activities, key=lambda row: row['comment']))


def inspect_owned_container(identity, project):
    info = json.loads(run('docker', 'inspect', identity))[0]
    ensure(info['Config']['Labels']['com.docker.compose.project'] == project)
    ensure(not info['HostConfig']['Binds'] and not info['HostConfig']['PortBindings'])
    return info


def probe(host):
    """The caller supplies only the inspected private lab address."""
    with requests.Session() as session:
        session.trust_env = False

        def call(method, path, body=None, expected=200):
            response = session.request(method, host + path, json=body,
                timeout=(3, 30), allow_redirects=False)
            if response.status_code != expected:
                raise RuntimeError('Owned interest probe unexpected HTTP status')
            return response.json()

        user = call('POST', '/api/v1/user', {}, 201)
        token = user['authToken']
        session.headers['Authorization'] = 'Bearer ' + token
        call('PUT', '/api/v1/user/setting', {'baseCurrency': 'EUR'})
        account = call('POST', '/api/v1/account', {'name': 'Synthetic interest policy',
            'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
        base = {'accountId': account['id'], 'currency': 'EUR', 'dataSource': 'MANUAL',
            'date': '2025-06-01T10:00:00+00:00', 'fee': 0, 'quantity': 1,
            'symbol': 'GF_DEGIRO_123_FLATEX_INTEREST_EUR', 'type': 'INTEREST'}
        activities = [{**base, 'comment': 'DEGIRO#123:INTEREST:101', 'unitPrice': 10},
                      {**base, 'comment': 'DEGIRO#123:INTEREST:102', 'unitPrice': 0}]
        config = {'ghost_host': host, 'ghost_token': token, 'dry_run': True}
        proposed, ok = core.ghost_import_activities(config, activities)
        ensure(ok is True and proposed == activities)
        ensure(call('GET', '/api/v1/activities')['count'] == 0)
        preview = call('POST', '/api/v1/import?dryRun=true', {'activities': activities}, 201)
        ensure(core.accepted_import_subset(activities, preview) == activities)
        ensure(call('GET', '/api/v1/activities')['count'] == 0)
        created = call('POST', '/api/v1/import', {'activities': activities}, 201)
        ensure(core.accepted_import_subset(activities, created) == activities)
        listed = call('GET', '/api/v1/activities')
        verify_stored(activities, listed)
        ensure({row['comment'] for row in listed['activities']} == {a['comment'] for a in activities})
        for row in listed['activities']:
            ensure(row['type'] == 'INTEREST' and row['accountId'] == account['id'])
            ensure(row['assetProfile']['dataSource'] == 'MANUAL')
            ensure(row['assetProfile']['symbol'] == base['symbol'])
        repeat = call('POST', '/api/v1/import', {'activities': activities}, 201)
        ensure(core.accepted_import_subset(activities, repeat) == [])
        for field in ('quantity', 'unitPrice', 'fee'):
            invalid = [{**activities[0], field: -1, 'comment': 'DEGIRO#123:INTEREST:999'}]
            call('POST', '/api/v1/import?dryRun=true', {'activities': invalid}, 400)
            ensure(call('GET', '/api/v1/activities')['count'] == 2)
        distinct = [{**activities[0], 'comment': 'DEGIRO#123:INTEREST:103'}]
        accepted = call('POST', '/api/v1/import', {'activities': distinct}, 201)
        ensure(core.accepted_import_subset(distinct, accepted) == distinct)
        accounts = call('GET', '/api/v1/account')['accounts']
        current = next(row for row in accounts if row['id'] == account['id'])
        ensure(current['interestInBaseCurrency'] == 20 and current['balance'] == 0)
        final = call('GET', '/api/v1/activities')
        verify_stored(activities + distinct, final)
        return {'positive_and_zero_accepted': True, 'preview_created': 0,
            'repeat_created': 0, 'negative_quantity_price_fee_rejected': True,
            'distinct_same_second_created': 1, 'interest_total_eur': 20,
            'balance_eur': 0, 'created': 3, 'immutable_core_evidence': True}


def interest(project, directory, state):
    password = secrets.token_hex(24)
    services = {
        'postgres': {'image': POSTGRES_IMAGE, 'networks': ['lab'],
            'tmpfs': ['/var/lib/postgresql/data'],
            'environment': {'POSTGRES_DB': 'interestlab', 'POSTGRES_USER': 'interestlab',
                            'POSTGRES_PASSWORD': password},
            'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U interestlab -d interestlab'],
                'interval': '1s', 'timeout': '3s', 'retries': 30}},
        'redis': {'image': REDIS_IMAGE, 'networks': ['lab']},
        'ghostfolio': {'image': GHOST_IMAGE, 'networks': ['lab'],
            'depends_on': {'postgres': {'condition': 'service_healthy'},
                           'redis': {'condition': 'service_started'}},
            'environment': {'DATABASE_URL': 'postgresql://interestlab:' + password + '@postgres:5432/interestlab',
                'ACCESS_TOKEN_SALT': secrets.token_hex(32), 'JWT_SECRET_KEY': secrets.token_hex(32),
                'NODE_ENV': 'production', 'REDIS_HOST': 'redis', 'REDIS_PORT': '6379'}}}
    compose = directory / 'compose.yaml'
    compose.write_text(yaml.safe_dump({'name': project,
        'networks': {'lab': {'internal': True}}, 'services': services}))
    compose.chmod(0o600)
    command = compose_command(project, compose)
    run(*command, 'up', '-d', '--pull', 'never', timeout=120)
    identities = {name: run(*command, 'ps', '-q', name).strip() for name in services}
    info = {name: inspect_owned_container(identity, project)
            for name, identity in identities.items()}
    ensure(info['ghostfolio']['Config']['Image'] == GHOST_IMAGE)
    network = project + '_lab'
    ensure(json.loads(run('docker', 'network', 'inspect', network))[0]['Internal'] is True)
    host = 'http://' + info['ghostfolio']['NetworkSettings']['Networks'][network]['IPAddress'] + ':3333'
    sql = ['docker', 'exec', '-i', identities['postgres'], 'psql', '-U', 'interestlab',
           '-d', 'interestlab', '-v', 'ON_ERROR_STOP=1', '-At']
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            ensure(run(*sql, input_text='SELECT count(*) FROM "Order";\n').strip() == '0')
            with requests.Session() as readiness:
                readiness.trust_env = False
                response = readiness.get(host + '/api/v1/health', timeout=(3, 3), allow_redirects=False)
                if response.status_code == 200:
                    break
        except (RuntimeError, AssertionError, requests.RequestException):
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('Owned interest instance not ready')
    print(json.dumps(probe(host), sort_keys=True), flush=True)


def main():
    project = 'degiro-interest-' + uuid.uuid4().hex[:12]
    lab_cleanup.execute(project, lambda directory, state: interest(project, directory, state))


if __name__ == '__main__':
    main()
