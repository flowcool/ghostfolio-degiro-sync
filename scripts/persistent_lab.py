#!/usr/bin/env python3
"""Scoped native checks on the inspected lab; never fetches broker data."""
from collections import Counter
from copy import deepcopy
import argparse
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import stat
import sys
import uuid

import requests
import yaml

sys.path.insert(0, '/app')
import degiro_to_ghostfolio as adapter
import ghostfolio_core as core


HOST = 'http://ghostfolio:3333'


def require(condition):
    if not condition:
        raise RuntimeError('Persistent lab evidence differs; private details suppressed')


def load_replay(root, digest):
    manifest = yaml.safe_load(adapter.read_private_evidence(root / 'manifest.yaml', digest))
    require(manifest['version'] == 1 and set(manifest['inputs']) == {'broker', 'destination', 'mapping'})
    values = {}
    for name, binding in manifest['inputs'].items():
        filename = name + ('.yaml' if name == 'mapping' else '.json')
        require(binding['path'] == filename)
        raw = adapter.read_private_evidence(root / filename, binding['sha256'])
        values[name] = (yaml.safe_load(raw) if name == 'mapping' else
            json.loads(raw, object_pairs_hook=adapter.unique_evidence_pairs))
    mapping, quotes = adapter.verified_mapping_document(values['mapping'])
    adapter.read_private_evidence(root / 'profiles.json', manifest['profiles_sha256'])
    return manifest, values['broker'], values['destination'], mapping, quotes


def synthetic(fixture, account_id):
    """Reuse the existing public synthetic fixture and native opening10/SELL2 case."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    event = now - timedelta(days=1)
    data = deepcopy(fixture)
    data['account_info'] = {'baseCurrency': 'EUR'}
    data['transactions'][0]['date'] = event.isoformat()
    data['cash_movements'] = [data['cash_movements'][name] for name in
        ('paid_dividend', 'dividend_withholding', 'trade_commission', 'exchange_connection_fee')]
    data['cash_movements'].append({'id': 110, 'type': 'TRANSACTION', 'productId': 20,
        'description': 'Vente 2 TEST', 'currency': 'USD', 'change': 20})
    for row in data['cash_movements']:
        row['date'] = row['valueDate'] = event.isoformat()
    data['update'] = deepcopy(data['current_cash'])
    data['update']['portfolio']['value'].append({'id': '20', 'name': 'positionrow',
        'value': [{'name': 'id', 'value': '20'}, {'name': 'size', 'value': 8}]})
    today = now.astimezone(adapter.ZoneInfo('Europe/Zurich')).date()
    data.update(from_date=(today - timedelta(days=89)).isoformat(), to_date=today.isoformat(),
        fetch_started_at=(now - timedelta(seconds=1)).isoformat(), fetched_at=now.isoformat(),
        history_completeness_verified=False)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['Date', 'Heure', 'Date de', 'Produit', 'Code ISIN', 'Description',
        'FX', 'Mouvements', '', 'Solde', '', 'ID Ordre'])
    for row in data['cash_movements']:
        product = data['products'].get(str(row.get('productId')), {})
        writer.writerow([event.strftime('%d-%m-%Y'), event.strftime('%H:%M'),
            event.strftime('%d-%m-%Y'), 'Synthetic', product.get('isin', ''), row['description'],
            '', row['currency'], str(row['change']).replace('.', ','), 'EUR', '0,00', row.get('orderId', '')])
    data['account_report_csv'] = stream.getvalue()
    seed = {'accountId': account_id, 'comment': 'Protected synthetic opening',
        'currency': 'USD', 'dataSource': 'YAHOO', 'date': '2020-01-01T00:00:00Z',
        'fee': 0, 'quantity': 10, 'symbol': 'TEST', 'type': 'BUY', 'unitPrice': 1}
    return data, [seed], {'US0378331005': 'TEST'}, {'TEST': 'USD'}


def remap_seeds(destination, new_account):
    original = destination['account']
    existing, unused = adapter.existing_activity_context(destination['activities'], original)
    return [{**{key: row[key] for key in adapter.TRADE_FIELDS}, 'accountId': new_account}
        for row in existing if row['accountId'] == original['id']]


def records(body, account):
    rows, unused = adapter.existing_activity_context(body, account)
    return {row['id']: adapter.activity_signature(row) for row in rows
        if row['accountId'] == account['id']}


def lifecycle(config, snapshot, mapping, quotes, call, expected, lose_reply=False, expected_cash=None):
    """Use unchanged account orchestration/core; only the broker read and clock are frozen."""
    target = call('GET', '/api/v1/account/' + config['target_account'])
    before = call('GET', '/api/v1/activities')
    protected = records(before, target)
    now = adapter.prospective_instant(snapshot['fetched_at'])

    def sync(cfg, lost=False):
        account = call('GET', '/api/v1/account/' + cfg['target_account'])
        body = call('GET', '/api/v1/activities')
        with adapter.ghost_transport(cfg, account):
            def importer(batch):
                accepted, ok = core.ghost_import_activities(cfg, batch)
                require(ok is True and len(accepted) == len(batch))
                if lost:
                    raise requests.Timeout('Synthetic lost acknowledgement after confirmed lab commit')
                return accepted, ok
            return adapter.synchronize_account(cfg, snapshot, account, body, mapping, quotes,
                importer, lambda identity, amount: core.ghost_update_cash_balance(cfg, identity, amount), now=now)

    preview = sync(config)
    require(preview['rolling_verified'] and not preview['history_verified']
        and preview['accepted'] == [] and len(preview['proposed']) == len(expected))
    require(expected_cash is None or preview['cash'] == expected_cash)
    require(Counter(map(adapter.activity_signature, preview['proposed'])) ==
        Counter(map(adapter.activity_signature, expected)))
    require(call('GET', '/api/v1/activities') == before)
    require(call('GET', '/api/v1/account/' + config['target_account']) == target)
    config = {**config, 'dry_run': False}
    if lose_reply:
        try:
            sync(config, lost=True)
        except RuntimeError as error:
            require(str(error) == 'Account import uncertain or incomplete; cash blocked')
        else:
            raise RuntimeError('Lab lost-response case did not fence import')
        with adapter.account_journal(config) as journal:
            require(journal['document']['pending']['kind'] == 'import')
        # Restart context: reread the destination, without previous process flags.
        config = {key: value for key, value in config.items() if not key.startswith('_')}
    sync(config)
    first = call('GET', '/api/v1/activities')
    stored = records(first, target)
    require(all(stored.get(identity) == signature for identity, signature in protected.items()))
    added = {identity: value for identity, value in stored.items() if identity not in protected}
    require(Counter(added.values()) == Counter(map(adapter.activity_signature, expected)))
    require(call('GET', '/api/v1/account/' + config['target_account'])['balance'] == preview['cash'])
    repeated = sync(config)
    require(repeated['proposed'] == [] and repeated['accepted'] == [])
    require(records(call('GET', '/api/v1/activities'), target) == stored)
    with adapter.account_journal(config) as journal:
        require(journal['document']['pending'] is None)
    return {'proposed': len(expected), 'created': len(added), 'repeat_created': 0,
        'protected': len(protected), 'cash_verified': True, 'history_verified': False,
        'frozen_capture_clock': snapshot['fetched_at'], 'positive_restart_verified': lose_reply}


def execute(args):
    require(os.environ.get('DEGIRO_PERSISTENT_LAB') == 'persistent-v1')
    require(not any(os.environ.get(key) for key in
        ('DEGIRO_USERNAME', 'DEGIRO_PASSWORD', 'DEGIRO_TOTP_SECRET', 'GHOST_TOKEN', 'APPRISE_URLS')))
    root = Path('/captures')
    manifest, broker, destination, mapping, quotes = load_replay(root, args.manifest_sha256)
    runs = Path('/runs')
    info = runs.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077)
    output = runs / str(uuid.uuid4())
    output.mkdir(mode=0o700)
    state = output / 'state'
    state.mkdir(mode=0o700)
    evidence = {'version': 1, 'scenario': args.scenario, 'manifest_sha256': args.manifest_sha256,
        'stage': 'prepared', 'production': False}

    def save():
        temporary = output / 'run.next.yaml'
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600), 'w') as stream:
            yaml.safe_dump(evidence, stream)
        os.replace(temporary, output / 'run.yaml')

    save()
    with requests.Session() as session:
        session.trust_env = False
        def call(method, path, body=None, status=200):
            response = session.request(method, HOST + path, json=body,
                timeout=(3, 30), allow_redirects=False)
            if response.status_code != status:
                evidence['failure'] = {'http_status': response.status_code, 'method': method,
                    'endpoint': '/'.join(path.split('/')[:4])}
                save()
            require(response.status_code == status)
            return response.json()
        call('GET', '/api/v1/health')
        user = call('POST', '/api/v1/user', {}, 201)
        session.headers['Authorization'] = 'Bearer ' + user['authToken']
        evidence.update(stage='user-created', user_id=call('GET', '/api/v1/user')['id'])
        save()
        call('PUT', '/api/v1/user/setting', {'baseCurrency': 'EUR'})
        account = call('POST', '/api/v1/account', {'name': 'DEGIRO lab ' + args.scenario + ' ' + output.name,
            'currency': 'EUR', 'balance': destination['account']['balance'] if args.scenario == 'replay' else 0,
            'platformId': None}, 201)
        evidence.update(stage='account-created', account_id=account['id'])
        save()
        if args.scenario == 'synthetic':
            snapshot, seeds, mapping, quotes = synthetic(yaml.safe_load(Path('/lab/fixture.yaml').read_text()), account['id'])
            expected = None
        else:
            snapshot = broker
            seeds = remap_seeds(destination, account['id'])
            require(len(seeds) == manifest['seed_count'])
            expected = [{**row, 'accountId': account['id']} for row in manifest['expected_proposals']]
        if seeds:
            call('POST', '/api/v1/import', {'activities': seeds}, 201)
        actual = records(call('GET', '/api/v1/activities'), account)
        require(Counter(actual.values()) == Counter(map(adapter.activity_signature, seeds)))
        evidence.update(stage='seed-verified', seed_count=len(seeds))
        save()
        config = {'ghost_host': HOST, 'ghost_token': user['authToken'],
            'source_account': snapshot['source_account'], 'target_account': account['id'],
            'sync_mode': 'rolling', 'dry_run': True, 'state_dir': str(state)}
        if expected is None:
            expected = adapter.synchronize_locked(config, snapshot, account,
                call('GET', '/api/v1/activities'), mapping, quotes, None, None,
                now=adapter.prospective_instant(snapshot['fetched_at']))['proposed']
            require(len(expected) == 3)
        evidence['result'] = lifecycle(config, snapshot, mapping, quotes, call, expected,
            lose_reply=args.scenario == 'synthetic',
            expected_cash=manifest['expected_cash'] if args.scenario == 'replay' else None)
    # Verify mounted evidence after use. Do not alter originals or remove lab resources.
    load_replay(root, args.manifest_sha256)
    evidence['stage'] = 'complete'
    save()
    print('PASS persistent lab; evidence retained; no broker reads or resource cleanup')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=('synthetic', 'replay'))
    parser.add_argument('--manifest-sha256', required=True)
    try:
        execute(parser.parse_args())
        return 0
    except Exception:
        print('Persistent lab verification failed; private details suppressed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
