"""Offline account orchestration and bounded immutable-core transport."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import requests
import yaml

import degiro_to_ghostfolio as adapter
import ghostfolio_core as core


NOW = datetime(2026, 10, 8, 20, tzinfo=timezone.utc)
TARGET = {'id': 'target-a', 'currency': 'EUR', 'name': 'Synthetic', 'balance': 0}
MAPPING = {'US0378331005': 'TEST'}
QUOTES = {'TEST': 'USD'}


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['account_info'] = {'baseCurrency': 'EUR'}
    data['update'] = deepcopy(data['current_cash'])
    data['cash_movements'] = [data['cash_movements'][name]
        for name in ('paid_dividend', 'dividend_withholding', 'trade_commission', 'exchange_connection_fee')]
    for row in data['cash_movements']:
        row.setdefault('valueDate', row['date'])
    data['fetch_started_at'] = (NOW - timedelta(seconds=30)).isoformat()
    data['fetched_at'] = (NOW - timedelta(seconds=10)).isoformat()
    data['history_completeness_verified'] = True
    return data


def activity_row(activity, identity='existing'):
    row = {**activity, 'id': identity, 'assetProfile': {
        'symbol': activity['symbol'], 'dataSource': activity['dataSource']}}
    row.pop('symbol')
    row.pop('dataSource')
    return row


def opening_holding():
    return activity_row({'accountId': 'target-a', 'comment': None, 'currency': 'USD',
        'dataSource': 'YAHOO', 'date': '2020-01-01T00:00:00Z', 'fee': 0,
        'quantity': 10, 'symbol': 'TEST', 'type': 'BUY', 'unitPrice': 1}, 'opening')


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setenv('STATE_DIR', str(tmp_path))
    tmp_path.chmod(0o700)


def run(snapshot, existing=None, dry_run=True, importer=None, writer=None, config=None):
    import os
    rows = [opening_holding()] if existing is None else existing
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': dry_run} if config is None else config
    config.setdefault('state_dir', os.environ['STATE_DIR'])
    config.setdefault('ghost_host', 'http://localhost:3333')
    return adapter.synchronize_account(config, snapshot, TARGET,
        {'activities': rows, 'count': len(rows)}, MAPPING, QUOTES,
        importer or (lambda activities: pytest.fail('Unexpected POST')),
        writer or (lambda *args: pytest.fail('Unexpected PUT')), now=NOW)


def test_dry_run_proposes_all_types_without_mutation(snapshot):
    result = run(snapshot)
    assert {a['type'] for a in result['proposed']} == {'SELL', 'DIVIDEND', 'FEE'}
    assert result['accepted'] == [] and result['cash'] == 12.3 and result['dry_run'] is True


def test_complete_first_run_and_zero_candidates_on_repeat(snapshot):
    stored = [opening_holding()]
    posted = []
    cash = []
    def post(activities):
        posted.extend(activities)
        first_id = len(stored)
        stored.extend(activity_row(a, str(first_id + i)) for i, a in enumerate(activities))
        return deepcopy(activities), True
    first = run(snapshot, stored, False, post, lambda *args: cash.append(args) or True)
    assert len(first['accepted']) == 3
    assert [a['type'] for a in posted] == ['DIVIDEND', 'FEE', 'SELL']
    second = run(snapshot, stored)
    assert second['proposed'] == [] and cash == [('target-a', 12.3)]


def test_identical_pending_duplicates_are_kept_once(snapshot):
    snapshot['transactions'].append(deepcopy(snapshot['transactions'][0]))
    assert len(run(snapshot)['proposed']) == 3


@pytest.mark.parametrize('mutation', ['unknown', 'unsupported', 'currency', 'fee', 'history', 'source'])
def test_whole_account_validation_precedes_post(snapshot, mutation):
    if mutation == 'unknown':
        snapshot['cash_movements'][0]['description'] = 'Unknown'
    elif mutation == 'unsupported':
        snapshot['cash_movements'].append({'id': 500, 'type': 'CASH_TRANSACTION',
            'description': 'Flatex Interest Income', 'change': 1, 'currency': 'EUR',
            'date': '2026-01-01T00:00:00Z', 'valueDate': '2026-01-01T00:00:00Z'})
    elif mutation == 'currency':
        snapshot['account_info']['baseCurrency'] = 'USD'
    elif mutation == 'fee':
        snapshot['cash_movements'][-1]['change'] = 2.5
    elif mutation == 'history':
        snapshot['history_completeness_verified'] = False
    else:
        snapshot['source_account'] = '456'
    with pytest.raises(RuntimeError):
        run(snapshot, dry_run=False)


@pytest.mark.parametrize('category,amount', [('flatex_interest', 10),
    ('flatex_interest', -10), ('monetary_fund_compensation', 0),
    ('monetary_fund_compensation', -10)])
def test_accounting_policy_blocks_all_writes_for_unsupported_movement(snapshot, category, amount):
    evidence = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    movement = deepcopy(evidence['cash_movements'][category])
    movement['change'] = amount
    movement.setdefault('valueDate', movement['date'])
    snapshot['cash_movements'].append(movement)
    attempted = []

    def forbidden(*args):
        attempted.append(args)
        pytest.fail('Unsupported accounting movement reached financial dispatch')

    with pytest.raises(RuntimeError):
        run(snapshot, dry_run=False, importer=forbidden, writer=forbidden)
    assert attempted == []


def test_dry_run_discloses_unverified_history(snapshot):
    snapshot['history_completeness_verified'] = False
    assert run(snapshot)['history_verified'] is False


@pytest.mark.parametrize('field,value', [('quantity', None), ('fee', None), ('unitPrice', None),
    ('assetProfile', None), ('date', None), ('isExcluded', True), ('isDraft', True),
    ('isExcluded', 'false'), ('tags', None), ('type', 'INTEREST')])
def test_redacted_inactive_or_unknown_target_context_blocks(snapshot, field, value):
    existing = [opening_holding()]
    existing[0][field] = value
    with pytest.raises(RuntimeError):
        run(snapshot, existing, dry_run=False)


def test_count_mismatch_and_duplicate_created_ids_block(snapshot):
    row = opening_holding()
    with pytest.raises(RuntimeError, match='Incomplete'):
        adapter.existing_activity_context({'activities': [row], 'count': 2}, TARGET)
    with pytest.raises(RuntimeError, match='Duplicate'):
        adapter.existing_activity_context({'activities': [row, row], 'count': 2}, TARGET)


def test_foreign_account_canonical_ownership_blocks(snapshot):
    fee = adapter.normalize_fees(snapshot, TARGET['id'])[0]
    fee['accountId'] = 'other-account'
    with pytest.raises(RuntimeError, match='another target'):
        run(snapshot, [opening_holding(), activity_row(fee, 'foreign')], dry_run=False)


def test_existing_identity_cannot_change_mapping_or_amount(snapshot):
    trade = adapter.normalize_trades(snapshot, TARGET['id'], MAPPING, QUOTES)[0]
    row = activity_row(trade, 'canonical')
    row['fee'] = 99
    with pytest.raises(RuntimeError, match='changed financial'):
        run(snapshot, [opening_holding(), row], dry_run=False)
    row['fee'] = trade['fee']
    row['assetProfile']['symbol'] = 'CHANGED'
    with pytest.raises(RuntimeError):
        run(snapshot, [opening_holding(), row], dry_run=False)


@pytest.mark.parametrize('dry_run', [True, False])
def test_changed_configured_mapping_preserves_native_shaped_existing_rows(snapshot, tmp_path, dry_run):
    canonical = adapter.normalize_trades(snapshot, TARGET['id'], MAPPING, QUOTES)[0]
    existing = {'activities': [opening_holding(), activity_row(canonical, 'canonical')], 'count': 2}
    before = deepcopy(existing)
    config = {'source_account': '123', 'target_account': TARGET['id'],
        'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path), 'dry_run': dry_run}

    def forbidden(*args):
        pytest.fail('Changed mapping reached a financial callback')

    with pytest.raises(RuntimeError, match='^Existing DEGIRO identity changed financial evidence$'):
        adapter.synchronize_account(config, snapshot, TARGET, existing,
            {'US0378331005': 'CHANGED_TEST'}, {'CHANGED_TEST': 'USD'},
            forbidden, forbidden, now=NOW)
    assert existing == before
    with adapter.account_journal(config) as journal:
        assert journal['document']['pending'] is None


def test_unrelated_crypto_context_is_preserved_without_blocking_target(snapshot):
    foreign = opening_holding()
    foreign.update(id='crypto', accountId='unrelated')
    foreign['assetProfile'] = {'symbol': 'bitcoin', 'dataSource': 'COINGECKO'}
    rows, holdings = adapter.existing_activity_context(
        {'activities': [opening_holding(), foreign], 'count': 2}, TARGET)
    assert rows[1]['dataSource'] == 'COINGECKO'
    assert holdings == {('target-a', 'TEST'): 10}
    assert len(run(snapshot, [opening_holding(), foreign])['proposed']) == 3


def test_crypto_provider_never_weakens_foreign_canonical_ownership(snapshot):
    fee = adapter.normalize_fees(snapshot, TARGET['id'])[0]
    fee.update(accountId='other-account', dataSource='COINGECKO')
    with pytest.raises(RuntimeError, match='another target'):
        run(snapshot, [opening_holding(), activity_row(fee, 'foreign')], dry_run=False)


@pytest.mark.parametrize('source', ['COINGECKO', '', None, 42])
def test_unsupported_target_data_source_blocks(snapshot, source):
    row = opening_holding()
    row['assetProfile']['dataSource'] = source
    with pytest.raises(RuntimeError):
        run(snapshot, [row], dry_run=False)


@pytest.mark.parametrize('field,value', [('symbol', ''), ('dataSource', ''), ('dataSource', None)])
def test_foreign_profile_still_requires_well_formed_evidence(snapshot, field, value):
    foreign = opening_holding()
    foreign.update(id='foreign', accountId='other-account')
    foreign['assetProfile'][field] = value
    with pytest.raises(RuntimeError):
        run(snapshot, [opening_holding(), foreign], dry_run=False)


def test_manual_csv_fee_overlap_requires_explicit_reconciliation(snapshot):
    fee = adapter.normalize_fees(snapshot, TARGET['id'])[0]
    fee['comment'] = None
    with pytest.raises(RuntimeError, match='Manual or CSV'):
        run(snapshot, [opening_holding(), activity_row(fee, 'manual')], dry_run=False)


@pytest.mark.parametrize('result', [([], True), ([], False), (None, True)])
def test_short_or_degraded_acceptance_fences_cash(snapshot, result):
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False}
    with pytest.raises(RuntimeError, match='cash blocked'):
        run(snapshot, dry_run=False, importer=lambda activities: result, config=config)
    assert config['_uncertain_import_accounts'] == {'target-a'}


def test_lost_response_fences_cash(snapshot):
    def post(activities):
        raise requests.Timeout('SECRET-SENTINEL')
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False}
    with pytest.raises(RuntimeError) as error:
        run(snapshot, dry_run=False, importer=post, config=config)
    assert 'SECRET' not in str(error.value)
    assert config['_uncertain_import_accounts'] == {'target-a'}


def test_accepted_buys_must_fund_later_sells(snapshot):
    buy = deepcopy(snapshot['transactions'][0])
    buy.update(id=9, buysell='B', quantity=2, total=-20, totalInBaseCurrency=-18.18,
        date='2026-01-01T10:00:00+01:00')
    snapshot['transactions'].insert(0, buy)
    snapshot['cash_movements'] = [r for r in snapshot['cash_movements'] if r['id'] == 104]
    calls = []
    def accepted(activities):
        calls.append([a['type'] for a in activities])
        return deepcopy(activities), True
    result = run(snapshot, [], False, accepted, lambda *args: True)
    assert calls == [['BUY', 'FEE'], ['SELL']]
    assert len(result['accepted']) == 3
    calls.clear()
    with pytest.raises(RuntimeError, match='cash blocked'):
        run(snapshot, [], False, lambda batch: (calls.append(batch) or [], True))
    assert len(calls) == 1 and all(a['type'] != 'SELL' for a in calls[0])


@pytest.mark.parametrize('url', ['https://evil.example', 'http://ghost.mylittlemess.fr',
    'https://ghost.mylittlemess.fr/', 'https://user:pass@ghost.mylittlemess.fr',
    'https://ghost.mylittlemess.fr?token=SECRET', 'http://127.0.0.1:9999', None])
def test_exact_target_origin_policy(url):
    with pytest.raises(RuntimeError) as error:
        adapter.validate_ghost_host(url)
    assert 'SECRET' not in str(error.value) and 'pass' not in str(error.value)


def response(body=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body or {}).encode()
    return result


def transport_config(dry_run=True):
    return {'ghost_host': 'http://localhost:3333', 'ghost_token': 'TOKEN-SENTINEL', 'dry_run': dry_run}


def test_transport_dry_run_blocks_every_mutation(monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, 'send', lambda self, req, **kw: calls.append(req) or response())
    original = core.requests
    with adapter.ghost_transport(transport_config(), TARGET) as session:
        assert core.requests is session
        for method, path in [('POST', '/api/v1/import'), ('PUT', '/api/v1/account/target-a'),
                             ('DELETE', '/api/v1/activities/created')]:
            with pytest.raises(RuntimeError, match='boundary'):
                session.request(method, 'http://localhost:3333' + path)
    assert calls == [] and core.requests is original


def test_transport_bounds_http_and_restores_core(monkeypatch):
    calls = []
    def send(self, req, **kw):
        calls.append((req, kw))
        return response({'activities': [], 'count': 0})
    monkeypatch.setattr(requests.Session, 'send', send)
    with adapter.ghost_transport(transport_config(), TARGET) as session:
        assert session.trust_env is False
        session.get('http://localhost:3333/api/v1/activities')
    req, options = calls[0]
    assert req.headers['Authorization'] == 'Bearer TOKEN-SENTINEL'
    assert options['timeout'] == (10, 60) and options['verify'] is True
    assert options['allow_redirects'] is False and options['stream'] is False


@pytest.mark.parametrize('url', ['https://evil.example/api/v1/activities',
    'http://localhost:3333/api/v1/activities?take=1', 'http://localhost:3333/api/v1/order',
    'http://localhost:3333/api/v1/account/other'])
def test_transport_refuses_other_origin_route_or_query(monkeypatch, url):
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kw: pytest.fail('Boundary bypass'))
    with adapter.ghost_transport(transport_config(False), TARGET) as session:
        with pytest.raises(RuntimeError, match='boundary'):
            session.get(url)


def test_core_cash_writer_rechecks_current_currency_before_put(monkeypatch):
    calls = []
    def send(self, req, **kw):
        calls.append(req.method)
        return response({**TARGET, 'currency': 'USD'})
    monkeypatch.setattr(requests.Session, 'send', send)
    config = transport_config(False)
    with adapter.ghost_transport(config, TARGET):
        with pytest.raises(RuntimeError, match='changed'):
            core.ghost_update_cash_balance(config, 'target-a', 12.3)
    assert calls == ['GET']


def test_transport_redirect_and_error_logs_do_not_expose_secrets(monkeypatch, caplog):
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kw: response({'secret': 'BODY-SENTINEL'}, 302))
    config = transport_config(False)
    fee = {'accountId': 'target-a', 'comment': 'DEGIRO#123:FEE:104', 'symbol': 'GF_TEST'}
    with adapter.ghost_transport(config, TARGET):
        imported, ok = core.ghost_import_activities(config, [fee])
    assert imported == [] and ok is False
    assert config['_uncertain_import_accounts'] == {'target-a'}
    assert 'TOKEN-SENTINEL' not in caplog.text and 'BODY-SENTINEL' not in caplog.text


def configure(monkeypatch, tmp_path, dry_run=None):
    path = tmp_path / 'mapping.yaml'
    path.write_text(yaml.safe_dump({'US0378331005': {'symbol': 'TEST', 'currency': 'USD'}}))
    for name, value in {'GHOST_HOST': 'http://localhost:3333', 'GHOST_TOKEN': 'TOKEN-SENTINEL',
        'GHOST_ACCOUNT_ID': 'target-a', 'DEGIRO_ACCOUNT_ID': '123', 'MAPPING_FILE': str(path)}.items():
        monkeypatch.setenv(name, value)
    if dry_run is None:
        monkeypatch.delenv('DRY_RUN', raising=False)
    else:
        monkeypatch.setenv('DRY_RUN', dry_run)
    return path


def test_config_is_env_only_and_defaults_dry_run(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    config, mapping, quotes = adapter.load_sync_config()
    assert config['dry_run'] is True and config['ghost_token'] == 'TOKEN-SENTINEL'
    assert mapping == MAPPING and quotes == QUOTES


@pytest.mark.parametrize('name,value', [('GHOST_HOST', 'https://evil.example'),
    ('GHOST_TOKEN', ''), ('GHOST_TOKEN', 'SECRET\nHEADER'), ('GHOST_ACCOUNT_ID', '../other'),
    ('DEGIRO_ACCOUNT_ID', '0'), ('DRY_RUN', 'maybe')])
def test_invalid_config_rejected_before_broker_read(monkeypatch, tmp_path, name, value):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: pytest.fail('Invalid config contacted broker'))
    with pytest.raises(RuntimeError):
        adapter.run_sync(NOW.date(), NOW.date())


@pytest.mark.parametrize('document', [None, {}, {'US0378331006': {'symbol': 'TEST', 'currency': 'USD'}},
    {'US0378331005': 'TEST'}, {'US0378331005': {'symbol': 'TEST', 'currency': 'GBp'}},
    {'US0378331005': {'symbol': ' TEST ', 'currency': 'USD'}},
    {'US0378331005': {'symbol': 'TEST', 'currency': 'USD', 'password': 'FAKE'}}])
def test_mapping_requires_explicit_verified_units(monkeypatch, tmp_path, document):
    path = configure(monkeypatch, tmp_path)
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(RuntimeError, match='mapping'):
        adapter.load_sync_config()


def test_mocked_http_end_to_end_dry_run_has_gets_only(snapshot, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    snapshot['fetch_started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    snapshot['fetched_at'] = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: snapshot)
    calls = []
    def send(self, req, **kw):
        calls.append((req.method, req.path_url))
        if req.path_url == '/api/v1/account/target-a':
            return response(TARGET)
        return response({'activities': [opening_holding()], 'count': 1})
    monkeypatch.setattr(requests.Session, 'send', send)
    result = adapter.run_sync(NOW.date(), NOW.date())
    assert len(result['proposed']) == 3 and result['accepted'] == []
    assert calls == [('GET', '/api/v1/account/target-a'), ('GET', '/api/v1/activities')]


def test_mocked_live_http_exact_acceptance_before_cash(snapshot, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, '0')
    snapshot['fetch_started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    snapshot['fetched_at'] = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: snapshot)
    calls = []
    def send(self, req, **kw):
        calls.append((req.method, req.path_url))
        if req.method == 'POST':
            submitted = json.loads(req.body)['activities']
            return response({'activities': [activity_row(a, str(i)) for i, a in enumerate(submitted)]}, 201)
        if req.method == 'PUT':
            body = json.loads(req.body)
            assert body == {'balance': 12.3, 'currency': 'EUR', 'id': 'target-a',
                'name': 'Synthetic', 'platformId': None}
            return response(TARGET)
        return response(TARGET if req.path_url.endswith('/target-a') else {'activities': [opening_holding()], 'count': 1})
    monkeypatch.setattr(requests.Session, 'send', send)
    result = adapter.run_sync(NOW.date(), NOW.date())
    assert len(result['accepted']) == 3
    assert [method for method, path in calls] == ['GET', 'GET', 'POST', 'POST', 'GET', 'PUT']


def test_unresolved_symbol_degrades_and_blocks_cash(snapshot, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, '0')
    snapshot['fetch_started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    snapshot['fetched_at'] = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: snapshot)
    posts = []
    def send(self, req, **kw):
        if req.method == 'POST':
            activities = json.loads(req.body)['activities']
            posts.append(activities)
            if len(posts) == 1:
                return response({'message': ['symbol ("TEST") cannot be resolved by the data source ("YAHOO")']}, 400)
            return response({'activities': [activity_row(a, str(i)) for i, a in enumerate(activities)]}, 201)
        if req.method != 'GET':
            pytest.fail('Degraded import attempted PUT/DELETE')
        return response(TARGET if req.path_url.endswith('/target-a') else {'activities': [opening_holding()], 'count': 1})
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(RuntimeError, match='cash blocked'):
        adapter.run_sync(NOW.date(), NOW.date())
    assert len(posts) == 2 and all(a['symbol'] != 'TEST' for a in posts[1])


def test_other_400_fails_without_symbol_retry(snapshot, monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kw: calls.append(True) or response({'message': ['invalid MANUAL symbol']}, 400))
    config = transport_config(False)
    fee = adapter.normalize_fees(snapshot, TARGET['id'])
    with adapter.ghost_transport(config, TARGET):
        created, ok = core.ghost_import_activities(config, fee)
    assert created == [] and ok is False and len(calls) == 1


@pytest.mark.parametrize('field,value', [('isExcluded', True), ('isExcluded', 'false'),
    ('tags', [{'id': 'f2e868af-8333-459f-b161-cbc6544c24bd'}]), ('balance', None),
    ('balance', True), ('id', 'other-account')])
def test_fresh_cash_read_rejects_changed_account_context(monkeypatch, field, value):
    calls = []
    monkeypatch.setattr(requests.Session, 'send', lambda self, req, **kw:
        calls.append(req.method) or response({**TARGET, field: value}))
    config = transport_config(False)
    with adapter.ghost_transport(config, TARGET):
        with pytest.raises(RuntimeError):
            core.ghost_update_cash_balance(config, 'target-a', 12.3)
    assert calls == ['GET']


def test_transport_failure_is_sanitized_and_restores_logger(monkeypatch, caplog):
    def fail(*args, **kw):
        raise requests.Timeout('TOKEN-SENTINEL BODY-SENTINEL https://credential@private')
    monkeypatch.setattr(requests.Session, 'send', fail)
    previous = core.requests
    disabled = core.log.disabled
    with pytest.raises(requests.RequestException) as error:
        with adapter.ghost_transport(transport_config(), TARGET) as session:
            session.get('http://localhost:3333/api/v1/activities')
    assert str(error.value) == 'Ghostfolio bounded transport failed'
    assert core.requests is previous and core.log.disabled is disabled
    assert 'SENTINEL' not in caplog.text


def test_cli_unverified_history_is_nonzero_and_never_reports_live_success(monkeypatch, caplog):
    monkeypatch.setattr(adapter, 'run_sync', lambda *args: {
        'dry_run': True, 'proposed': [], 'accepted': [], 'history_verified': False})
    assert adapter.main(['--sync', '--from-date', '2026-01-01', '--to-date', '2026-01-02']) == 1
    assert 'unverified' in caplog.text


def test_cli_errors_are_fixed_and_preclude_private_exception_text(monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError('TOKEN-SENTINEL BODY-SENTINEL')
    monkeypatch.setattr(adapter, 'run_sync', fail)
    assert adapter.main(['--sync', '--from-date', '2026-01-01', '--to-date', '2026-01-02']) == 1
    assert 'SENTINEL' not in caplog.text


def test_prior_uncertainty_fences_all_callbacks(snapshot):
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False,
        '_uncertain_import_accounts': {'target-a'}}
    with pytest.raises(RuntimeError, match='prior import'):
        run(snapshot, config=config)


def test_cron_default_dates_are_bounded_utc_lookback(monkeypatch):
    monkeypatch.setenv('LOOKBACK_DAYS', '90')
    calls = []
    monkeypatch.setattr(adapter, 'run_sync', lambda start, end, window:
        calls.append((start, end, window)) or {'dry_run': True, 'proposed': [],
            'accepted': [], 'history_verified': True})
    assert adapter.main(['--sync']) == 0
    start, end, window = calls[0]
    assert end == datetime.now(timezone.utc).date()
    assert (end - start).days == 89 and window == 90


@pytest.mark.parametrize('lookback', ['1', '367', 'invalid', 'true'])
def test_invalid_cron_lookback_never_runs_sync(monkeypatch, lookback):
    monkeypatch.setenv('LOOKBACK_DAYS', lookback)
    monkeypatch.setattr(adapter, 'run_sync', lambda *args: pytest.fail('Invalid lookback ran sync'))
    assert adapter.main(['--sync']) == 1


def test_read_only_still_requires_dates_before_broker_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: pytest.fail('Missing dates contacted broker'))
    assert adapter.main(['--read-only', '--output', str(tmp_path / 'private.json')]) == 1
