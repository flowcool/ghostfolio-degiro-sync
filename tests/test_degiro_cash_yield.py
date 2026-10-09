"""Offline cash-yield policy, account ownership and durable recovery regressions."""
from copy import deepcopy

import pytest

import degiro_to_ghostfolio as adapter
from test_degiro_sync import NOW, TARGET, activity_row, run, snapshot, private_state


def yield_row(kind='compensation', identity=601, amount=None):
    return {'id': identity, 'type': 'COMPENSATION_BOOKING' if kind == 'compensation' else 'CASH_TRANSACTION',
        'description': 'Compensation Fonds Monétaires DEGIRO' if kind == 'compensation' else 'Flatex Interest Income',
        'change': (2.5 if kind == 'compensation' else 0) if amount is None else amount,
        'currency': 'EUR', 'date': '2025-06-01T12:00:00+02:00',
        'valueDate': '2025-06-01T00:00:00+02:00'}


def yield_snapshot(snapshot):
    snapshot['transactions'] = []
    snapshot['cash_movements'] = [yield_row(), yield_row('interest', 602)]
    return snapshot


def test_distinct_yield_identities_preserve_exact_credit_and_zero_notice(snapshot):
    data = yield_snapshot(snapshot)
    activities = adapter.normalize_cash_yield(data, TARGET['id'])
    compensation, interest = activities
    assert compensation == {'accountId': TARGET['id'], 'comment': 'DEGIRO#123:COMPENSATION:601',
        'currency': 'EUR', 'dataSource': 'MANUAL', 'date': '2025-06-01T10:00:00+00:00',
        'fee': 0, 'quantity': 1, 'symbol': 'GF_DEGIRO_123_MMF_COMPENSATION_EUR',
        'type': 'INTEREST', 'unitPrice': 2.5}
    assert interest['comment'] == 'DEGIRO#123:INTEREST:602'
    assert interest['symbol'] == 'GF_DEGIRO_123_FLATEX_INTEREST_EUR'
    assert interest['quantity'] == 1 and interest['unitPrice'] == interest['fee'] == 0
    assert data['cash_movements'][0]['date'] == '2025-06-01T12:00:00+02:00'


def test_whole_account_dry_run_and_repeat_include_zero_interest(snapshot):
    data = yield_snapshot(snapshot)
    first = run(data, [])
    assert len(first['proposed']) == 2 and first['accepted'] == []
    assert first['cash'] == 12.3
    stored = [activity_row(a, str(i)) for i, a in enumerate(first['proposed'])]
    assert run(data, stored)['proposed'] == []


def test_live_mocked_acceptance_updates_snapshot_cash_once(snapshot):
    data = yield_snapshot(snapshot)
    stored, cash = [], []
    def post(batch):
        stored.extend(activity_row(a, str(len(stored) + i)) for i, a in enumerate(batch))
        return deepcopy(batch), True
    first = run(data, stored, False, post, lambda account, amount: cash.append((account, amount)) or True)
    assert len(first['accepted']) == 2 and cash == [(TARGET['id'], 12.3)]
    assert run(data, stored)['proposed'] == []


@pytest.mark.parametrize('field,value', [('change', -1), ('change', 0), ('change', 0.001),
    ('change', None), ('change', True), ('change', float('nan')), ('currency', 'USD'),
    ('productId', 20), ('orderId', 'unverified'), ('exchangeRate', 1), ('tax', 0),
    ('date', '2025-06-01'), ('valueDate', None), ('id', 0),
    ('description', 'Compensation Fonds Monétaires DEGIRO annulation'), ('type', 'CASH_TRANSACTION')])
def test_uncharacterized_credit_blocks_every_financial_callback(snapshot, field, value):
    data = yield_snapshot(snapshot)
    data['cash_movements'][0][field] = value
    with pytest.raises(RuntimeError):
        run(data, [], False)


@pytest.mark.parametrize('amount', [-1, .01, 10])
def test_unobserved_nonzero_flatex_interest_blocks(snapshot, amount):
    data = yield_snapshot(snapshot)
    data['cash_movements'][1]['change'] = amount
    with pytest.raises(RuntimeError, match='cash yield'):
        run(data, [], False)


def test_base_currency_and_target_currency_remain_proved(snapshot):
    data = yield_snapshot(snapshot)
    data['account_info']['baseCurrency'] = 'USD'
    with pytest.raises(RuntimeError):
        run(data, [], False)
    with pytest.raises(RuntimeError, match='account currency'):
        adapter.normalize_cash_yield(data, TARGET['id'])


def test_yield_support_does_not_relax_history_completeness(snapshot):
    data = yield_snapshot(snapshot)
    data['history_completeness_verified'] = False
    assert run(data, [])['history_verified'] is False
    with pytest.raises(RuntimeError, match='history completeness'):
        run(data, [], False)


def test_future_yield_blocks_dispatch(snapshot):
    data = yield_snapshot(snapshot)
    data['cash_movements'][0]['date'] = '2099-01-01T00:00:00Z'
    with pytest.raises(RuntimeError, match='Future'):
        run(data, [], False)


def test_yield_identities_include_source_and_target_context(snapshot):
    data = yield_snapshot(snapshot)
    first = adapter.normalize_cash_yield(data, TARGET['id'])
    data['source_account'] = '456'
    other = adapter.normalize_cash_yield(data, 'other-target')
    assert {a['comment'] for a in first}.isdisjoint(a['comment'] for a in other)
    assert {a['symbol'] for a in first}.isdisjoint(a['symbol'] for a in other)
    assert all(a['accountId'] == 'other-target' for a in other)


def test_same_second_same_amount_different_cash_ids_are_preserved(snapshot):
    data = yield_snapshot(snapshot)
    data['cash_movements'].append(yield_row(identity=603))
    data['cash_movements'].append(deepcopy(data['cash_movements'][0]))
    activities = run(data, [])['proposed']
    assert len(activities) == 3
    assert len({a['comment'] for a in activities}) == 3
    data['cash_movements'][-1]['change'] = 3
    with pytest.raises(RuntimeError, match='Conflicting'):
        run(data, [])


@pytest.mark.parametrize('field,value', [('accountId', 'other-account'), ('unitPrice', 3),
    ('currency', 'USD'), ('quantity', 2), ('fee', 1), ('type', 'DIVIDEND'),
    ('symbol', 'GF_CHANGED'), ('dataSource', 'YAHOO'), ('date', '2025-06-02T10:00:00Z')])
def test_changed_or_foreign_canonical_credit_never_reimports(snapshot, field, value):
    data = yield_snapshot(snapshot)
    row = adapter.normalize_cash_yield(data, TARGET['id'])[0]
    row[field] = value
    with pytest.raises(RuntimeError):
        run(data, [activity_row(row)], False)


def test_existing_zero_interest_cannot_become_nonzero_even_without_source_row(snapshot):
    data = yield_snapshot(snapshot)
    row = adapter.normalize_cash_yield(data, TARGET['id'])[1]
    row['unitPrice'] = 1
    data['cash_movements'] = []
    with pytest.raises(RuntimeError, match='canonical'):
        run(data, [activity_row(row)], False)


@pytest.mark.parametrize('index', [0, 1], ids=['compensation', 'zero-interest'])
def test_existing_canonical_yield_requires_original_symbol_without_source_row(snapshot, index):
    data = yield_snapshot(snapshot)
    row = adapter.normalize_cash_yield(data, TARGET['id'])[index]
    row['symbol'] = 'GF_CHANGED'
    data['cash_movements'] = []
    with pytest.raises(RuntimeError, match='canonical DEGIRO cash yield'):
        run(data, [activity_row(row)], False)


def test_existing_interest_requires_manual_profile_without_canonical_comment(snapshot):
    data = yield_snapshot(snapshot)
    row = adapter.normalize_cash_yield(data, TARGET['id'])[0]
    row.update(comment=None, dataSource='YAHOO', symbol='TEST')
    data['cash_movements'] = []
    with pytest.raises(RuntimeError, match='target interest representation'):
        run(data, [activity_row(row)], False)


def test_manual_interest_overlap_blocks_despite_different_custom_symbol(snapshot):
    data = yield_snapshot(snapshot)
    row = adapter.normalize_cash_yield(data, TARGET['id'])[0]
    row.update(comment=None, symbol='GF_MANUAL_OLD')
    with pytest.raises(RuntimeError, match='Manual or CSV'):
        run(data, [activity_row(row)], False)


def test_uncertain_yield_import_is_durably_fenced_and_exact_readback_recovers(snapshot, tmp_path):
    data = yield_snapshot(snapshot)
    stored = []
    config = {'source_account': '123', 'target_account': TARGET['id'], 'dry_run': False,
        'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path)}
    def lost(batch):
        stored.extend(activity_row(a, str(i)) for i, a in enumerate(batch))
        raise TimeoutError('PRIVATE-SENTINEL')
    with pytest.raises(RuntimeError, match='cash blocked') as error:
        run(data, stored, False, lost, config=config)
    assert 'PRIVATE' not in str(error.value)
    with adapter.account_journal(config) as journal:
        intent = journal['document']['pending']['id']
    with pytest.raises(RuntimeError, match='durable'):
        run(data, stored, False, config=config)
    body = {'count': len(stored), 'activities': stored}
    broken = deepcopy(body)
    broken['activities'][0]['unitPrice'] += 1
    with pytest.raises(RuntimeError):
        adapter.resolve_import_intent(config, broken, expected_intent_id=intent)
    assert adapter.resolve_import_intent(config, body, expected_intent_id=intent) == 2
    clean_config = {key: value for key, value in config.items() if key != '_uncertain_import_accounts'}
    clean_config['dry_run'] = True
    assert run(data, stored, config=clean_config)['proposed'] == []


def test_cleanup_preflight_requires_exact_yield_manifest_and_target_ownership(snapshot):
    data = yield_snapshot(snapshot)
    activities = adapter.normalize_cash_yield(data, TARGET['id'])
    body = {'count': 2, 'activities': [activity_row(a, str(i)) for i, a in enumerate(activities)]}
    manifest = {'source_account': '123', 'target_account': TARGET['id'],
        'activities': {a['comment']: a for a in activities}}
    selected = adapter.cleanup_preflight(body, manifest)
    assert selected['activity_ids'] == {'DEGIRO#123:COMPENSATION:601': '0', 'DEGIRO#123:INTEREST:602': '1'}
    body['activities'][0]['accountId'] = 'foreign'
    with pytest.raises(RuntimeError):
        adapter.cleanup_preflight(body, manifest)
