#!/usr/bin/env python3
"""Synthetic disposable-server checks; invoked only by isolated_acceptance.py."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import csv
import io
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

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


def prospective_native_acceptance(call, mapping, quotes):
    """Native prospective lifecycle over a closed synthetic broker baseline."""
    fixture = yaml.safe_load(Path('/lab/fixture.yaml').read_text())
    now = datetime.now(timezone.utc)
    cutover = (now - timedelta(days=2)).replace(microsecond=0)
    account = call('POST', '/api/v1/account', {'name': 'Synthetic prospective',
        'currency': 'EUR', 'balance': 12.3, 'platformId': None}, 201)
    opening_activity = {'accountId': account['id'], 'comment': 'Protected prospective legacy',
        'currency': 'USD', 'dataSource': 'YAHOO', 'date': '2020-01-01T00:00:00Z',
        'fee': 0, 'quantity': 10, 'symbol': 'TEST', 'type': 'BUY', 'unitPrice': 1}
    call('POST', '/api/v1/import', {'activities': [opening_activity]}, 201)
    directory = Path(tempfile.mkdtemp(prefix='prospective-'))
    state = directory / 'state'
    state.mkdir(mode=0o700)
    baseline = {'source_account': '905', 'account_info': {'baseCurrency': 'EUR'},
        'transactions': [], 'cash_movements': [], 'products': fixture['products'],
        'update': deepcopy(fixture['current_cash']),
        'from_date': cutover.astimezone(adapter.ZoneInfo('Europe/Zurich')).date().isoformat(),
        'to_date': cutover.astimezone(adapter.ZoneInfo('Europe/Zurich')).date().isoformat(),
        'fetch_started_at': (cutover - timedelta(seconds=2)).isoformat(),
        'fetched_at': cutover.isoformat(), 'history_completeness_verified': False}
    baseline['update']['portfolio']['value'].append({'id': '20', 'name': 'positionrow',
        'value': [{'name': 'id', 'value': '20'}, {'name': 'size', 'value': 10}]})
    destination = {'account': call('GET', '/api/v1/account/' + account['id']),
        'activities': call('GET', '/api/v1/activities'),
        'captured_at': (cutover - timedelta(seconds=1)).isoformat()}
    # Times describe the closed synthetic baseline, never a real historical capture.
    manifest = {'version': 1, 'source_account': '905', 'target_account': account['id'],
        'cutover': cutover.isoformat(), 'basis_status': 'unverified',
        'mapping_sha256': adapter.evidence_digest({'mapping': mapping, 'quote_currencies': quotes}),
        'opening': {}}
    for name, value in (('broker', baseline), ('destination', destination)):
        raw = json.dumps(value).encode()
        path = directory / (name + '.json')
        path.write_bytes(raw)
        path.chmod(0o600)
        manifest['opening'][name] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
    manifest_path = directory / 'manifest.yaml'
    raw = yaml.safe_dump(manifest).encode()
    manifest_path.write_bytes(raw)
    manifest_path.chmod(0o600)
    config = {'ghost_host': HOST, 'ghost_token': os.environ['GHOST_TOKEN'],
        'source_account': '905', 'target_account': account['id'], 'dry_run': True,
        'sync_mode': 'prospective', 'cutover_manifest': str(manifest_path),
        'cutover_sha256': hashlib.sha256(raw).hexdigest(), 'state_dir': str(state)}
    data = deepcopy(baseline)
    data['transactions'] = deepcopy(fixture['transactions'])
    trade_time = (cutover + timedelta(minutes=20)).isoformat()
    data['transactions'][0]['date'] = trade_time
    data['cash_movements'] = [deepcopy(fixture['cash_movements'][name]) for name in (
        'paid_dividend', 'dividend_withholding', 'trade_commission', 'exchange_connection_fee')]
    for row in data['cash_movements']:
        row['date'] = trade_time if row['id'] == 103 else (cutover + timedelta(minutes=30)).isoformat()
        row['valueDate'] = row['date']
    data['cash_movements'].append({'id': 110, 'type': 'TRANSACTION', 'productId': 20,
        'description': 'Vente 2 TEST', 'change': 20, 'currency': 'USD',
        'date': trade_time, 'valueDate': trade_time})
    data['update']['portfolio']['value'][-1]['value'][-1]['value'] = 8
    def statement():
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['Date', 'Heure', 'Date de', 'Produit', 'Code ISIN', 'Description',
            'FX', 'Mouvements', '', 'Solde', '', 'ID Ordre'])
        for row in data['cash_movements']:
            instant = datetime.fromisoformat(row['date'])
            value = datetime.fromisoformat(row['valueDate'])
            product = data['products'].get(str(row.get('productId')), {})
            writer.writerow([instant.strftime('%d-%m-%Y'), instant.strftime('%H:%M'),
                value.strftime('%d-%m-%Y'), 'Synthetic', product.get('isin', ''), row['description'],
                '', row['currency'], str(row['change']).replace('.', ','), 'EUR', '0,00', row.get('orderId', '')])
        return stream.getvalue()
    def sync(importer=None):
        now = datetime.now(timezone.utc)
        data['fetch_started_at'] = (now - timedelta(seconds=1)).isoformat()
        data['fetched_at'] = now.isoformat()
        data['to_date'] = now.astimezone(adapter.ZoneInfo('Europe/Zurich')).date().isoformat()
        data['account_report_csv'] = statement()
        target = call('GET', '/api/v1/account/' + account['id'])
        body = call('GET', '/api/v1/activities')
        with adapter.ghost_transport(config, target):
            return adapter.synchronize_account(config, data, target, body, mapping, quotes,
                importer or (lambda batch: core.ghost_import_activities(config, batch)),
                lambda identity, amount: core.ghost_update_cash_balance(config, identity, amount))
    before = deepcopy(destination['activities'])
    preview = sync()
    assert preview['prospective_verified'] and not preview['history_verified']
    assert len(preview['proposed']) == 3 and preview['accepted'] == []
    assert call('GET', '/api/v1/activities') == before
    config['dry_run'] = False
    first = sync()
    assert len(first['accepted']) == 3
    body = call('GET', '/api/v1/activities')
    normalized, quantities = adapter.existing_activity_context(body, account)
    assert quantities[(account['id'], 'TEST')] == 8
    actual = {row['comment']: adapter.activity_signature(row) for row in normalized
        if row['accountId'] == account['id'] and (row['comment'] or '').startswith('DEGIRO#')}
    assert actual == {row['comment']: adapter.activity_signature(row) for row in first['accepted']}
    preserved = [row for row in body['activities'] if row['id'] in {
        row['id'] for row in before['activities'] if row['accountId'] == account['id']}]
    def financial_records(body):
        normalized, unused = adapter.existing_activity_context(body, account)
        return {row['id']: adapter.activity_signature(row) for row in normalized
            if row['accountId'] == account['id']}
    protected_ids = {row['id'] for row in preserved}
    assert {key: value for key, value in financial_records(body).items() if key in protected_ids} == financial_records(before)
    assert sync()['accepted'] == []
    assert financial_records(call('GET', '/api/v1/activities')) == financial_records(body)
    assert call('GET', '/api/v1/account/' + account['id'])['balance'] == 12.3
    # Exercise native uncertain-result recovery, keeping the complete replay interval.
    extra = deepcopy(data['cash_movements'][3])
    extra['id'] = 1701
    extra['date'] = extra['valueDate'] = (cutover + timedelta(minutes=40)).isoformat()
    data['cash_movements'].append(extra)
    def lost_response(batch):
        accepted, ok = core.ghost_import_activities(config, batch)
        assert ok and len(accepted) == 1
        raise requests.Timeout('Synthetic prospective lost reply after commit')
    try:
        sync(lost_response)
    except RuntimeError as error:
        assert 'cash blocked' in str(error)
    else:
        raise AssertionError('Prospective uncertain response accepted')
    assert_restart_fenced(config, 'import')
    with adapter.account_journal(config) as journal:
        intent = journal['document']['pending']['id']
    assert adapter.resolve_import_intent(config, call('GET', '/api/v1/activities'),
        expected_intent_id=intent) == 1
    config.pop('_uncertain_import_accounts', None)
    assert sync()['accepted'] == []
    final = call('GET', '/api/v1/activities')
    assert final['count'] == body['count'] + 1
    assert {key: value for key, value in financial_records(final).items() if key in protected_ids} == financial_records(before)
    print('PASS prospective:verified opening10;SELL2/native holding8;3 exact activities;'
        'DRY_RUN zero writes;legacy unchanged;repeat zero;history/basis unverified;'
        'lost reply durable restart fence and exact recovery without replay', flush=True)


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

    def synchronize(snapshot, cfg, selected_mapping=None, selected_quotes=None):
        now = datetime.now(timezone.utc)
        snapshot['fetch_started_at'] = (now - timedelta(seconds=1)).isoformat()
        snapshot['fetched_at'] = now.isoformat()
        target = call('GET', '/api/v1/account/' + cfg['target_account'])
        existing = call('GET', '/api/v1/activities')
        with adapter.ghost_transport(cfg, target):
            return adapter.synchronize_account(cfg, snapshot, target, existing,
                mapping if selected_mapping is None else selected_mapping,
                quotes if selected_quotes is None else selected_quotes,
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

    mapping_before = call('GET', '/api/v1/activities')
    balance_before = call('GET', '/api/v1/account/' + account['id'])['balance']
    try:
        synchronize(data, config, {'US0378331005': 'CHANGED_TEST'}, {'CHANGED_TEST': 'USD'})
    except RuntimeError as error:
        assert str(error) == 'Existing DEGIRO identity changed financial evidence'
    else:
        raise AssertionError('Changed mapping silently adopted an existing canonical activity')
    assert call('GET', '/api/v1/activities') == mapping_before
    assert call('GET', '/api/v1/account/' + account['id'])['balance'] == balance_before
    with adapter.account_journal(config) as journal:
        assert journal['document']['pending'] is None
    print('PASS changed mapping: canonical identity conflict before dispatch;exact native rows and cash unchanged;no pending intent', flush=True)

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
    recovery_environment = {**os.environ, 'GHOST_HOST': HOST, 'GHOST_ACCOUNT_ID': account['id'],
        'DEGIRO_ACCOUNT_ID': config['source_account'], 'STATE_DIR': config['state_dir']}
    recovery_command = [sys.executable, '/app/scripts/recover_degiro.py',
        '--expected-intent-id', delayed_intent_id]
    preflight = subprocess.run(recovery_command, env=recovery_environment,
        capture_output=True, text=True, timeout=150)
    assert preflight.returncode == 0 and '1 exact activities verified; intent retained' in preflight.stdout
    assert_restart_fenced(config, 'import')
    resolved = subprocess.run(recovery_command + ['--confirm-local-state'], env=recovery_environment,
        capture_output=True, text=True, timeout=150)
    assert resolved.returncode == 0 and '1 exact activities confirmed locally' in resolved.stdout
    assert synchronize(delayed, config)['proposed'] == []
    assert call('GET', '/api/v1/activities')['count'] == 5
    print('PASS delayed insertion: timeout then empty GET;restart no replay;release creates exactly1;old request ID refused;selected positive readback resolves;repeat zero imports', flush=True)

    csv_account = call('POST', '/api/v1/account', {'name': 'Synthetic CSV overlap',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    csv_data = deepcopy(data)
    csv_data['source_account'] = '456'
    conversion = yaml.safe_load(Path('/lab/v3.yaml').read_text())
    csv_trade = deepcopy(conversion['cases']['foreign_fee']['output']['activities'][0])
    csv_trade['accountId'] = csv_account['id']
    csv_opening = {**opening, 'accountId': csv_account['id'], 'comment': 'Synthetic CSV opening'}
    call('POST', '/api/v1/import', {'activities': [csv_opening, csv_trade]}, 201)
    csv_readback = call('GET', '/api/v1/activities')
    csv_rows, _ = adapter.existing_activity_context(csv_readback, csv_account)
    native_csv = [row for row in csv_rows if row['accountId'] == csv_account['id']
                  and row['comment'] == csv_trade['comment']]
    assert len(native_csv) == 1
    assert adapter.activity_signature(native_csv[0]) == adapter.activity_signature(csv_trade)
    before_csv = call('GET', '/api/v1/activities')['count']
    csv_config = {**config, 'source_account': '456', 'target_account': csv_account['id']}
    try:
        synchronize(csv_data, csv_config)
        raise AssertionError('CSV overlap silently adopted or imported')
    except RuntimeError as error:
        assert 'Manual or CSV' in str(error)
    assert call('GET', '/api/v1/activities')['count'] == before_csv
    assert call('GET', '/api/v1/account/' + csv_account['id'])['balance'] == 0
    print('PASS actual pinned V3 synthetic SELL accepted unchanged;API overlap blocks account despite fee mismatch;zero added activities/cash writes;cleanup selects3 exact broker IDs only', flush=True)

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
    print('Stage: cash-yield native setup', flush=True)
    call('PUT', '/api/v1/user/setting', {'baseCurrency': 'EUR'})
    yield_account = call('POST', '/api/v1/account', {'name': 'Synthetic cash yield',
        'currency': 'EUR', 'balance': 0, 'platformId': None}, 201)
    yield_data = deepcopy(delayed)
    yield_data.update(source_account='904', transactions=[], cash_movements=[
        {'id': 1601, 'type': 'COMPENSATION_BOOKING',
         'description': 'Compensation Fonds Monétaires DEGIRO', 'currency': 'EUR', 'change': 2.5,
         'date': '2025-06-01T12:00:00+02:00', 'valueDate': '2025-06-01T00:00:00+02:00'},
        {'id': 1602, 'type': 'CASH_TRANSACTION',
         'description': 'Flatex Interest Income', 'currency': 'EUR', 'change': 0,
         'date': '2025-06-01T12:00:00+02:00', 'valueDate': '2025-06-01T00:00:00+02:00'},
        {'id': 1603, 'type': 'COMPENSATION_BOOKING',
         'description': 'Compensation Fonds Monétaires DEGIRO', 'currency': 'EUR', 'change': 2.5,
         'date': '2025-06-01T12:00:00+02:00', 'valueDate': '2025-06-01T00:00:00+02:00'}])
    yield_config = {key: value for key, value in config.items() if not key.startswith('_')}
    yield_config.update(source_account='904', target_account=yield_account['id'], dry_run=True)
    before_yield = call('GET', '/api/v1/activities')
    proposed_yield = synchronize(yield_data, yield_config)
    print('Stage: cash-yield dry run validated', flush=True)
    assert len(proposed_yield['proposed']) == 3 and proposed_yield['accepted'] == []
    assert call('GET', '/api/v1/activities') == before_yield
    assert call('GET', '/api/v1/account/' + yield_account['id'])['balance'] == 0
    yield_config['dry_run'] = False
    first_yield = synchronize(yield_data, yield_config)
    print('Stage: cash-yield first import returned', flush=True)
    assert len(first_yield['accepted']) == 3
    assert all(row['type'] == 'INTEREST' for row in first_yield['accepted'])
    assert sorted(row['unitPrice'] for row in first_yield['accepted']) == [0, 2.5, 2.5]
    print('Stage: cash-yield accepted values validated', flush=True)
    exact_yield = call('GET', '/api/v1/activities')
    yield_rows, _ = adapter.existing_activity_context(exact_yield, yield_account)
    print('Stage: cash-yield native context validated', flush=True)
    assert {a['comment']: adapter.activity_signature(a) for a in yield_rows
        if a['accountId'] == yield_account['id']} == {
        a['comment']: adapter.activity_signature(a) for a in first_yield['accepted']}
    print('Stage: cash-yield native financial signatures validated', flush=True)
    assert len(adapter.cleanup_preflight(exact_yield, {'source_account': '904',
        'target_account': yield_account['id'],
        'activities': {a['comment']: a for a in first_yield['accepted']}})['activity_ids']) == 3
    print('Stage: cash-yield cleanup ownership validated', flush=True)
    assert synchronize(yield_data, yield_config)['accepted'] == []
    repeated_yield = call('GET', '/api/v1/activities')
    repeated_yield_rows, _ = adapter.existing_activity_context(repeated_yield, yield_account)
    assert repeated_yield['count'] == exact_yield['count']
    assert {a['comment']: (a['id'], adapter.activity_signature(a)) for a in repeated_yield_rows
        if a['accountId'] == yield_account['id']} == {
        a['comment']: (a['id'], adapter.activity_signature(a)) for a in yield_rows
        if a['accountId'] == yield_account['id']}
    exact_yield = repeated_yield
    yield_totals = next(a for a in call('GET', '/api/v1/account')['accounts']
        if a['id'] == yield_account['id'])
    print('Stage: cash-yield exact rows and repeat validated', flush=True)
    assert yield_totals['interestInBaseCurrency'] == 5 and yield_totals['balance'] == 12.3

    for index, amount in ((0, -2.5), (1, .01)):
        invalid_yield = deepcopy(yield_data)
        invalid_yield['cash_movements'][index]['change'] = amount
        try:
            synchronize(invalid_yield, yield_config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Uncharacterized yield accepted')
        assert call('GET', '/api/v1/activities') == exact_yield
        assert call('GET', '/api/v1/account/' + yield_account['id'])['balance'] == 12.3
    lost_yield = deepcopy(yield_data)
    lost_yield['cash_movements'] = [deepcopy(yield_data['cash_movements'][0])]
    lost_yield['cash_movements'][0]['id'] = 1604
    now = datetime.now(timezone.utc)
    lost_yield['fetch_started_at'] = lost_yield['fetched_at'] = now.isoformat()
    def lost_yield_response(batch):
        accepted, ok = core.ghost_import_activities(yield_config, batch)
        assert ok and len(accepted) == 1
        raise requests.Timeout('Synthetic lost reply after commit')
    target_yield = call('GET', '/api/v1/account/' + yield_account['id'])
    with adapter.ghost_transport(yield_config, target_yield):
        try:
            adapter.synchronize_account(yield_config, lost_yield, target_yield, exact_yield,
                mapping, quotes, lost_yield_response,
                lambda *args: (_ for _ in ()).throw(AssertionError('Uncertain yield reached cash writer')))
        except RuntimeError as error:
            assert 'cash blocked' in str(error)
        else:
            raise AssertionError('Lost yield reply succeeded')
    assert_restart_fenced(yield_config, 'import')
    with adapter.account_journal(yield_config) as journal:
        yield_intent = journal['document']['pending']['id']
    assert adapter.resolve_import_intent(yield_config, call('GET', '/api/v1/activities'),
        expected_intent_id=yield_intent) == 1
    yield_config.pop('_uncertain_import_accounts', None)
    assert synchronize(lost_yield, yield_config)['accepted'] == []
    yield_final = next(a for a in call('GET', '/api/v1/account')['accounts']
        if a['id'] == yield_account['id'])
    assert yield_final['interestInBaseCurrency'] == 7.5 and yield_final['balance'] == 12.3
    print('PASS cash yield:zero interest retained;distinct same-second compensation;exact native readback;'
        'repeat zero;credit totals5/7.5 EUR;cash12.30 independently set;negative/nonzero-interest blocked;'
        'lost response restart fenced and exact recovery without replay;cleanup ownership verified', flush=True)
    prospective_native_acceptance(call, mapping, quotes)
    session.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Isolated acceptance failed; private HTTP/auth details suppressed', file=sys.stderr)
        for frame in traceback.extract_tb(sys.exc_info()[2]):
            print('Failure location: ' + Path(frame.filename).name + ':' + str(frame.lineno)
                + ':' + frame.name, file=sys.stderr)
        sys.exit(1)
