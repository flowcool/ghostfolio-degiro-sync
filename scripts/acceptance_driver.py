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


def assert_restart_fenced(config, kind):
    """Use a new interpreter; never copy credentials to the child input."""
    program = '''
import json, sys
import degiro_to_ghostfolio as adapter
config, kind = json.loads(sys.stdin.read())
with adapter.account_journal(config) as journal:
    assert journal['document']['pending']['kind'] == kind
try:
    adapter.synchronize_account(config, {}, {}, {}, {}, {}, None, None)
    raise AssertionError('Fresh process replay allowed')
except RuntimeError as error:
    assert 'durable write intent' in str(error)
print('FENCED')
'''
    safe = {key: value for key, value in config.items()
        if key != 'ghost_token' and not key.startswith('_')}
    result = subprocess.run([sys.executable, '-c', program], input=json.dumps([safe, kind]),
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'FENCED'


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
    with adapter.account_journal(config) as journal:
        delayed_intent_id = journal['document']['pending']['id']
        previous_intent_id = next(iter(journal['document']['resolved']))
    before = call('GET', '/api/v1/activities')
    assert before['count'] == 4
    try:
        adapter.resolve_import_intent(config, before, expected_intent_id=delayed_intent_id)
        raise AssertionError('Empty pending readback resolved delayed insertion')
    except RuntimeError:
        pass
    assert_restart_fenced(config, 'import')
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
    try:
        adapter.resolve_import_intent(config, after, expected_intent_id=previous_intent_id)
        raise AssertionError('Prior request selection resolved a later intent')
    except RuntimeError as error:
        assert str(error) == 'Synchronization intent identity changed'
    assert_restart_fenced(config, 'import')
    assert adapter.resolve_import_intent(config, after, expected_intent_id=delayed_intent_id) == 1
    assert synchronize(delayed, config)['proposed'] == []
    assert call('GET', '/api/v1/activities')['count'] == 5
    print('PASS delayed insertion: timeout then empty GET;restart no replay;release creates exactly1;old request ID refused;selected positive readback resolves;repeat zero imports', flush=True)

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
    with adapter.account_journal(unresolved_config) as journal:
        unresolved_intent_id = journal['document']['pending']['id']
    incomplete = call('GET', '/api/v1/activities')
    owned = [row for row in incomplete['activities'] if row['accountId'] == unresolved_account['id']]
    assert len(owned) == 1 and owned[0]['type'] == 'FEE'
    assert call('GET', '/api/v1/account/' + unresolved_account['id'])['balance'] == 0
    try:
        adapter.resolve_import_intent(unresolved_config, incomplete,
            expected_intent_id=unresolved_intent_id)
        raise AssertionError('Partial symbol retry cleared durable intent')
    except RuntimeError:
        pass
    print('PASS native unresolved-symbol400 retries only resolvable FEE;partial readback remains fenced;zero cash writes', flush=True)

    def barrier(stage, acknowledgement):
        print(stage, flush=True)
        if sys.stdin.readline().strip() != acknowledgement:
            raise RuntimeError('Owned recovery barrier not acknowledged')

    def wait_healthy():
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                call('GET', '/api/v1/health', timeout=2)
                return
            except (requests.RequestException, RuntimeError):
                time.sleep(.5)
        raise RuntimeError('Owned restarted server did not become healthy')

    partial_account = call('POST', '/api/v1/account', {'name': 'Synthetic partial cancellation',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    partial_data = deepcopy(delayed)
    partial_data['source_account'] = '901'
    partial_data['cash_movements'] = [{**partial_data['cash_movements'][0], 'id': identity}
        for identity in (1001, 1002)]
    partial_config = {**config, 'source_account': '901', 'target_account': partial_account['id']}
    partial_config.pop('_uncertain_import_accounts', None)
    barrier('ARM_BARRIER: import-partial', 'armed')
    now = datetime.now(timezone.utc)
    partial_data['fetch_started_at'] = partial_data['fetched_at'] = now.isoformat()
    try:
        adapter.synchronize_account(partial_config, partial_data,
            call('GET', '/api/v1/account/' + partial_account['id']), call('GET', '/api/v1/activities'),
            mapping, quotes, lambda batch: call('POST', '/api/v1/import', {'activities': batch}, 201, timeout=1),
            lambda *args: (_ for _ in ()).throw(AssertionError('Partial import attempted cash')))
        raise AssertionError('Partial import did not time out')
    except RuntimeError as error:
        assert 'cash blocked' in str(error)
    with adapter.account_journal(partial_config) as journal:
        partial_intent_id = journal['document']['pending']['id']
    partial_before = call('GET', '/api/v1/activities')
    partial_rows = [row for row in partial_before['activities'] if row['accountId'] == partial_account['id']]
    assert len(partial_rows) == 1 and partial_rows[0]['comment'] == 'DEGIRO#901:FEE:1001'
    assert_restart_fenced(partial_config, 'import')
    barrier('QUIESCENCE_READY: import-partial', 'quiescent')
    wait_healthy()
    partial_after = call('GET', '/api/v1/activities')
    assert partial_after['count'] == partial_before['count']
    assert [row for row in partial_after['activities'] if row['accountId'] == partial_account['id']] == partial_rows
    try:
        adapter.resolve_import_intent(partial_config, partial_after,
            expected_intent_id=partial_intent_id)
        raise AssertionError('Partial cancellation silently cleared intent')
    except RuntimeError:
        pass
    assert_restart_fenced(partial_config, 'import')
    print('PASS partial cancellation: sole owned app stopped;DB sessions terminated and zero verified;restart exact accepted subset unchanged;intent retained;no replay', flush=True)

    for source, amount, completion in (('902', 42.42, True), ('903', 84.84, False)):
        cash_account = call('POST', '/api/v1/account', {'name': 'Synthetic uncertain cash ' + source,
            'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
        cash_config = {**config, 'source_account': source, 'target_account': cash_account['id']}
        cash_config.pop('_uncertain_import_accounts', None)
        cash_data = deepcopy(delayed)
        cash_data.update(source_account=source, transactions=[], cash_movements=[])
        for row in cash_data['update']['totalPortfolio']['value']:
            if row['name'] in ('totalCash', 'flatexCash'):
                row['value'] = amount
        cash_data['update']['cashFunds']['value'][0]['value'][1]['value'] = amount
        cash_data['update']['portfolio']['value'][0]['value'][1]['value'] = amount
        now = datetime.now(timezone.utc)
        cash_data['fetch_started_at'] = cash_data['fetched_at'] = now.isoformat()
        barrier('ARM_BARRIER: cash', 'armed')

        def lost_cash(identity, balance):
            current = call('GET', '/api/v1/account/' + identity)
            payload = {key: current.get(key) for key in ('currency', 'id', 'name', 'platformId')}
            payload['balance'] = balance
            call('PUT', '/api/v1/account/' + identity, payload, timeout=1)
            raise AssertionError('Blocked cash unexpectedly returned')

        try:
            adapter.synchronize_account(cash_config, cash_data, call('GET', '/api/v1/account/' + cash_account['id']),
                call('GET', '/api/v1/activities'), mapping, quotes,
                lambda *args: (_ for _ in ()).throw(AssertionError('Cash-only scenario attempted import')), lost_cash)
            raise AssertionError('Uncertain cash falsely succeeded')
        except RuntimeError as error:
            assert 'Uncertain cash' in str(error)
        assert call('GET', '/api/v1/account/' + cash_account['id'])['balance'] == 0
        assert_restart_fenced(cash_config, 'cash')
        if completion:
            barrier('CASH_RELEASE_READY: cash', 'release')
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if call('GET', '/api/v1/account/' + cash_account['id'])['balance'] == amount:
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('Released cash update did not complete')
        else:
            barrier('QUIESCENCE_READY: cash', 'quiescent')
            wait_healthy()
            assert call('GET', '/api/v1/account/' + cash_account['id'])['balance'] == 0
        assert_restart_fenced(cash_config, 'cash')
        print('PASS uncertain cash: native PUT response lost;restart no replay;' +
            ('release changes balance exactly once;matching balance retains intent' if completion else
             'independent owned quiescence cancels delayed PUT;balance unchanged;intent retained'), flush=True)
    session.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Isolated acceptance failed; private HTTP/auth details suppressed', file=sys.stderr)
        sys.exit(1)
