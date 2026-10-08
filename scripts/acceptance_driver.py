#!/usr/bin/env python3
"""Synthetic disposable-server checks; invoked only by isolated_acceptance.py."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import requests
import yaml

sys.path.insert(0, '/app')
import degiro_to_ghostfolio as adapter
import ghostfolio_core as core


HOST = 'http://ghostfolio:3333'


def main():
    if os.environ.get('DEGIRO_ISOLATED_ACCEPTANCE') != 'synthetic-c13':
        raise RuntimeError('Owned isolated acceptance controller required')
    session = requests.Session()
    session.trust_env = False

    def call(method, path, payload=None, status=200, timeout=30):
        response = session.request(method, HOST + path, json=payload,
            timeout=timeout, allow_redirects=False)
        if response.status_code != status:
            raise RuntimeError('Isolated acceptance HTTP status ' + str(response.status_code))
        return response.json()

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            call('GET', '/api/v1/health', timeout=2)
            break
        except (requests.RequestException, RuntimeError):
            time.sleep(.5)
    else:
        raise RuntimeError('Owned isolated server did not become healthy')
    user = call('POST', '/api/v1/user', {}, 201)
    os.environ['GHOST_TOKEN'] = user['authToken']
    session.headers['Authorization'] = 'Bearer ' + os.environ['GHOST_TOKEN']
    account = call('POST', '/api/v1/account', {'name': 'Synthetic C13',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    data = yaml.safe_load(Path('/lab/fixture.yaml').read_text())
    data['account_info'] = {'baseCurrency': 'EUR'}
    data['update'] = deepcopy(data['current_cash'])
    data['cash_movements'] = [data['cash_movements'][name]
        for name in ('paid_dividend', 'dividend_withholding', 'trade_commission', 'exchange_connection_fee')]
    for row in data['cash_movements']:
        row.setdefault('valueDate', row['date'])
    data['history_completeness_verified'] = True  # Synthetic closed fixture only.
    state = tempfile.mkdtemp(prefix='c13-intent-')
    config = {'ghost_host': HOST, 'ghost_token': os.environ['GHOST_TOKEN'],
        'source_account': '123', 'target_account': account['id'], 'dry_run': True, 'state_dir': state}
    mapping, quotes = {'US0378331005': 'TEST'}, {'TEST': 'USD'}
    opening = {'accountId': account['id'], 'comment': 'Synthetic opening holding',
        'currency': 'USD', 'dataSource': 'YAHOO', 'date': '2020-01-01T00:00:00Z',
        'fee': 0, 'quantity': 10, 'symbol': 'TEST', 'type': 'BUY', 'unitPrice': 1}
    call('POST', '/api/v1/import', {'activities': [opening]}, 201)

    def synchronize(snapshot, cfg):
        now = datetime.now(timezone.utc)
        snapshot['fetch_started_at'] = (now - timedelta(seconds=1)).isoformat()
        snapshot['fetched_at'] = now.isoformat()
        target = call('GET', '/api/v1/account/' + cfg['target_account'])
        existing = call('GET', '/api/v1/activities')
        with adapter.ghost_transport(cfg, target):
            return adapter.synchronize_account(cfg, snapshot, target, existing, mapping, quotes,
                lambda batch: core.ghost_import_activities(cfg, batch),
                lambda identity, amount: core.ghost_update_cash_balance(cfg, identity, amount))

    preview = synchronize(data, config)
    assert len(preview['proposed']) == 3 and preview['accepted'] == []
    assert call('GET', '/api/v1/activities')['count'] == 1
    assert call('GET', '/api/v1/account/' + account['id'])['balance'] == 0
    config['dry_run'] = False
    first = synchronize(data, config)
    assert len(first['accepted']) == 3
    assert {a['type'] for a in first['accepted']} == {'SELL', 'DIVIDEND', 'FEE'}
    rows = call('GET', '/api/v1/activities')
    normalized, holdings = adapter.existing_activity_context(rows, account)
    assert rows['count'] == 4 and holdings[(account['id'], 'TEST')] == 8
    actual = {a['comment']: adapter.activity_signature(a) for a in normalized if a['comment'].startswith('DEGIRO#')}
    assert actual == {a['comment']: adapter.activity_signature(a) for a in first['accepted']}
    cleanup = adapter.cleanup_preflight(rows, {'source_account': '123', 'target_account': account['id'],
        'activities': {a['comment']: a for a in first['accepted']}})
    assert len(cleanup['activity_ids']) == 3
    assert opening['comment'] not in cleanup['activity_ids']
    assert call('GET', '/api/v1/account/' + account['id'])['balance'] == 12.3
    repeated = synchronize(data, config)
    assert repeated['proposed'] == [] and repeated['accepted'] == []
    assert call('GET', '/api/v1/activities')['count'] == 4
    print('PASS native import: DRY_RUN zero writes;3 exact activities;net holding8;cash12.30 EUR;repeat zero imports', flush=True)

    delayed = deepcopy(data)
    delayed['transactions'] = []
    delayed['cash_movements'] = [deepcopy(data['cash_movements'][-1])]
    delayed['cash_movements'][0]['id'] = 999
    fee = adapter.normalize_fees(delayed, account['id'])
    print('Stage: preparing delayed native import', flush=True)
    try:
        now = datetime.now(timezone.utc)
        delayed['fetch_started_at'] = delayed['fetched_at'] = now.isoformat()
        adapter.synchronize_account(config, delayed, call('GET', '/api/v1/account/' + account['id']),
            call('GET', '/api/v1/activities'), mapping, quotes,
            lambda batch: call('POST', '/api/v1/import', {'activities': batch}, 201, timeout=1),
            lambda *args: (_ for _ in ()).throw(AssertionError('Uncertain request attempted cash')))
        raise AssertionError('Delayed INSERT did not lose its response')
    except RuntimeError as error:
        assert 'cash blocked' in str(error)
    config.pop('_uncertain_import_accounts', None)
    print('Stage: checking unresolved readback', flush=True)
    before = call('GET', '/api/v1/activities')
    assert before['count'] == 4
    try:
        adapter.resolve_import_intent(config, before)
        raise AssertionError('Empty pending readback resolved delayed insertion')
    except RuntimeError:
        pass
    restart = '''
import json, sys
import degiro_to_ghostfolio as adapter
config = json.loads(sys.stdin.read())
with adapter.account_journal(config) as journal:
    assert journal['document']['pending']['kind'] == 'import'
try:
    adapter.synchronize_account(config, {}, {}, {}, {}, {}, None, None)
    raise AssertionError('Fresh process replay allowed')
except RuntimeError as error:
    assert 'durable write intent' in str(error)
print('FENCED')
'''
    restart_config = {key: value for key, value in config.items()
        if key != 'ghost_token' and not key.startswith('_')}
    result = subprocess.run([sys.executable, '-c', restart], input=json.dumps(restart_config),
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'FENCED'
    print('BARRIER_READY: empty readback and fresh process remain fenced', flush=True)
    if sys.stdin.readline().strip() != 'release':
        raise RuntimeError('Owned barrier release not acknowledged')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        after = call('GET', '/api/v1/activities')
        if after['count'] == 5:
            break
        time.sleep(.2)
    else:
        raise RuntimeError('Released delayed insertion did not finish')
    assert adapter.resolve_import_intent(config, after) == 1
    assert synchronize(delayed, config)['proposed'] == []
    assert call('GET', '/api/v1/activities')['count'] == 5
    print('PASS delayed insertion: timeout then empty GET;restart no replay;release creates exactly1;positive readback resolves;repeat zero imports', flush=True)

    csv_account = call('POST', '/api/v1/account', {'name': 'Synthetic CSV overlap',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    csv_data = deepcopy(data)
    csv_data['source_account'] = '456'
    csv_trade = adapter.normalize_trades(csv_data, csv_account['id'], mapping, quotes)[0]
    csv_trade['comment'] = None
    csv_opening = {**opening, 'accountId': csv_account['id'], 'comment': 'Synthetic CSV opening'}
    call('POST', '/api/v1/import', {'activities': [csv_opening, csv_trade]}, 201)
    before_csv = call('GET', '/api/v1/activities')['count']
    csv_config = {**config, 'source_account': '456', 'target_account': csv_account['id']}
    try:
        synchronize(csv_data, csv_config)
        raise AssertionError('CSV overlap silently adopted or imported')
    except RuntimeError as error:
        assert 'Manual or CSV' in str(error)
    assert call('GET', '/api/v1/activities')['count'] == before_csv
    assert call('GET', '/api/v1/account/' + csv_account['id'])['balance'] == 0
    print('PASS CSV-shaped unmarked trade overlap blocks whole API account;zero added activities/cash writes;cleanup selects3 exact broker IDs only', flush=True)

    unresolved_account = call('POST', '/api/v1/account', {'name': 'Synthetic unresolved symbol',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    unresolved_data = deepcopy(data)
    unresolved_data['source_account'] = '789'
    unresolved_data['transactions'][0].update(buysell='B', quantity=2, total=-20, totalInBaseCurrency=-18.18)
    unresolved_config = {**config, 'source_account': '789', 'target_account': unresolved_account['id']}
    now = datetime.now(timezone.utc)
    unresolved_data['fetch_started_at'] = unresolved_data['fetched_at'] = now.isoformat()
    unresolved_mapping, unresolved_quotes = {'US0378331005': 'UNRESOLVED_TEST'}, {'UNRESOLVED_TEST': 'USD'}
    target = call('GET', '/api/v1/account/' + unresolved_account['id'])
    try:
        with adapter.ghost_transport(unresolved_config, target):
            adapter.synchronize_account(unresolved_config, unresolved_data, target,
                call('GET', '/api/v1/activities'), unresolved_mapping, unresolved_quotes,
                lambda batch: core.ghost_import_activities(unresolved_config, batch),
                lambda *args: (_ for _ in ()).throw(AssertionError('Degraded import attempted cash')))
        raise AssertionError('Unresolved symbol falsely succeeded')
    except RuntimeError as error:
        assert 'cash blocked' in str(error)
    incomplete = call('GET', '/api/v1/activities')
    owned = [row for row in incomplete['activities'] if row['accountId'] == unresolved_account['id']]
    assert len(owned) == 1 and owned[0]['type'] == 'FEE'
    assert call('GET', '/api/v1/account/' + unresolved_account['id'])['balance'] == 0
    try:
        adapter.resolve_import_intent(unresolved_config, incomplete)
        raise AssertionError('Partial symbol retry cleared durable intent')
    except RuntimeError:
        pass
    print('PASS native unresolved-symbol400 retries only resolvable FEE;partial readback remains fenced;zero cash writes', flush=True)
    session.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Isolated acceptance failed; private HTTP/auth details suppressed', file=sys.stderr)
        sys.exit(1)
