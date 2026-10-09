"""Current cash evidence, freshness and zero-write failure/DRY_RUN boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter


NOW = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)
TARGET = {'id': 'target-a', 'currency': 'EUR'}


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['account_info'] = {'baseCurrency': 'EUR'}
    data['update'] = deepcopy(data['current_cash'])
    data['cash_movements'] = []
    data['fetch_started_at'] = (NOW - timedelta(seconds=30)).isoformat()
    data['fetched_at'] = (NOW - timedelta(seconds=10)).isoformat()
    return data


def extract(snapshot, target=None):
    return adapter.current_cash_balance(snapshot, TARGET if target is None else target, '123', NOW)


def set_total(snapshot, name, value):
    rows = snapshot['update']['totalPortfolio']['value']
    next(row for row in rows if row['name'] == name)['value'] = value


def test_aliases_are_crosschecks_not_amounts_to_sum(snapshot):
    snapshot['update']['totalPortfolio']['value'].append({'name': 'cryptoTotalCash', 'value': 12.3})
    snapshot['cash_movements'] = [{'id': 1, 'type': 'CASH_TRANSACTION', 'description': 'Retrait TEST',
        'change': -100, 'balance': 999999, 'currency': 'EUR', 'date': '2025-01-01T00:00:00Z',
        'valueDate': '2025-01-01T00:00:00Z'}]
    assert extract(snapshot) == 12.3


def test_zero_is_valid_and_distinct_from_missing(snapshot):
    for name in ('totalCash', 'flatexCash'):
        set_total(snapshot, name, 0)
    snapshot['update']['cashFunds']['value'][0]['value'][1]['value'] = 0
    snapshot['update']['portfolio']['value'][0]['value'][1]['value'] = 0
    assert extract(snapshot) == 0
    snapshot['update']['totalPortfolio']['value'][0]['value'] = None
    with pytest.raises(RuntimeError):
        extract(snapshot)


@pytest.mark.parametrize('name,value', [('totalCash', None), ('totalCash', True),
    ('totalCash', float('nan')), ('totalCash', float('inf')), ('totalCash', -1),
    ('totalCash', 12.301), ('totalCash', 13), ('degiroCash', 12.3),
    ('flatexCash', 0), ('pendingSettlement', 1), ('pendingSettlement', -1)])
def test_unverified_totals_block(snapshot, name, value):
    set_total(snapshot, name, value)
    with pytest.raises(RuntimeError):
        extract(snapshot)


@pytest.mark.parametrize('name', ['totalCash', 'degiroCash', 'flatexCash', 'pendingSettlement'])
def test_missing_or_duplicate_total_names_block(snapshot, name):
    rows = snapshot['update']['totalPortfolio']['value']
    found = next(row for row in rows if row['name'] == name)
    rows.append(deepcopy(found))
    with pytest.raises(RuntimeError, match='duplicate'):
        extract(snapshot)
    rows[:] = [row for row in rows if row['name'] != name]
    with pytest.raises(RuntimeError, match='Missing'):
        extract(snapshot)


@pytest.mark.parametrize('field,offset', [('fetch_started_at', -301), ('fetch_started_at', 1),
    ('fetched_at', -40), ('fetched_at', 1)])
def test_stale_slow_reversed_or_future_fetch_blocks(snapshot, field, offset):
    snapshot[field] = (NOW + timedelta(seconds=offset)).isoformat()
    with pytest.raises(RuntimeError, match='timing'):
        extract(snapshot)


def test_five_minute_boundary_and_explicit_offset(snapshot):
    snapshot['fetch_started_at'] = (NOW - timedelta(minutes=5)).isoformat()
    assert extract(snapshot) == 12.3
    snapshot['fetched_at'] = '2026-10-08T21:59:50+02:00'
    assert extract(snapshot) == 12.3
    snapshot['fetched_at'] = '2026-10-08T20:00:00'
    with pytest.raises(RuntimeError, match='offset'):
        extract(snapshot)


@pytest.mark.parametrize('now', [None, '2026-10-08', datetime(2026, 10, 8)])
def test_unusable_current_time_or_old_snapshot_blocks(snapshot, now):
    if now is None:
        snapshot['fetched_at'] = snapshot['fetch_started_at'] = '2000-01-01T00:00:00Z'
    with pytest.raises(RuntimeError):
        adapter.current_cash_balance(snapshot, TARGET, '123', now)


@pytest.mark.parametrize('target', [{}, {'id': '', 'currency': 'EUR'},
    {'id': 'target-a', 'currency': None}, {'id': 'target-a', 'currency': 'USD'}])
def test_missing_target_or_different_currency_blocks(snapshot, target):
    with pytest.raises(RuntimeError):
        extract(snapshot, target)


def test_source_identity_and_base_currency_must_match(snapshot):
    with pytest.raises(RuntimeError, match='source account'):
        adapter.current_cash_balance(snapshot, TARGET, '456', NOW)
    snapshot['account_info']['baseCurrency'] = 'USD'
    with pytest.raises(RuntimeError, match='currencies'):
        extract(snapshot)


@pytest.mark.parametrize('wrapper', ['totalPortfolio', 'cashFunds', 'portfolio'])
def test_missing_current_wrapper_never_falls_back_to_history(snapshot, wrapper):
    del snapshot['update'][wrapper]
    with pytest.raises(RuntimeError):
        extract(snapshot)


@pytest.mark.parametrize('wrapper', ['totalPortfolio', 'cashFunds', 'portfolio'])
@pytest.mark.parametrize('value', [False, None, 1, 'true'])
def test_removed_or_ambiguous_update_flags_block(snapshot, wrapper, value):
    snapshot['update'][wrapper]['isAdded'] = value
    with pytest.raises(RuntimeError, match='wrapper'):
        extract(snapshot)
    del snapshot['update'][wrapper]['isAdded']
    snapshot['update'][wrapper]['value'][0]['isAdded'] = value
    with pytest.raises(RuntimeError):
        extract(snapshot)


def test_incorrect_wrapper_name_blocks(snapshot):
    snapshot['update']['totalPortfolio']['name'] = 'history'
    with pytest.raises(RuntimeError, match='wrapper'):
        extract(snapshot)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'foreign', 'mismatch', 'invalid-code'])
def test_fund_evidence_must_be_unique_and_match(snapshot, mutation):
    rows = snapshot['update']['cashFunds']['value']
    if mutation == 'missing':
        rows.clear()
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif mutation == 'foreign':
        foreign = deepcopy(rows[0])
        foreign['value'][0]['value'] = 'USD'
        rows.append(foreign)
    elif mutation == 'mismatch':
        rows[0]['value'][1]['value'] = 1
    else:
        rows[0]['value'][0]['value'] = 'GBp'
    with pytest.raises(RuntimeError):
        extract(snapshot)


def test_zero_foreign_cash_is_accepted_without_conversion(snapshot):
    foreign = deepcopy(snapshot['update']['cashFunds']['value'][0])
    foreign['value'][0]['value'] = 'USD'
    foreign['value'][1]['value'] = 0
    snapshot['update']['cashFunds']['value'].append(foreign)
    assert extract(snapshot) == 12.3


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'size', 'id', 'duplicate-size'])
def test_flatex_pseudoposition_must_match(snapshot, mutation):
    rows = snapshot['update']['portfolio']['value']
    if mutation == 'missing':
        rows.clear()
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif mutation == 'size':
        rows[0]['value'][1]['value'] = 0
    elif mutation == 'id':
        rows[0]['value'][0]['value'] = 'WRONG'
    else:
        rows[0]['value'].append({'name': 'size', 'value': 12.3})
    with pytest.raises(RuntimeError):
        extract(snapshot)


def test_crypto_alias_is_not_extra_cash(snapshot):
    snapshot['update']['totalPortfolio']['value'].append({'name': 'cryptoTotalCash', 'value': 1})
    with pytest.raises(RuntimeError, match='alias'):
        extract(snapshot)


def test_foreign_pseudoposition_must_also_be_zero(snapshot):
    foreign = deepcopy(snapshot['update']['portfolio']['value'][0])
    foreign['id'] = foreign['value'][0]['value'] = 'FLATEX_USD'
    snapshot['update']['portfolio']['value'].append(foreign)
    with pytest.raises(RuntimeError, match='foreign'):
        extract(snapshot)
    foreign['value'][1]['value'] = 0
    assert extract(snapshot) == 12.3
    snapshot['update']['portfolio']['value'].append(deepcopy(foreign))
    with pytest.raises(RuntimeError, match='identity'):
        extract(snapshot)


def test_source_lastupdated_units_are_not_guessed(snapshot):
    for wrapper in snapshot['update'].values():
        if isinstance(wrapper, dict):
            wrapper['lastUpdated'] = 0
    assert extract(snapshot) == 12.3


def test_optional_accrued_interest_without_value_is_observed(snapshot):
    snapshot['update']['portfolio']['value'][0]['value'].append({'name': 'accruedInterest'})
    assert extract(snapshot) == 12.3
    snapshot['update']['portfolio']['value'][0]['value'][1].pop('value')
    with pytest.raises(RuntimeError):
        extract(snapshot)


def test_unknown_or_unsupported_ledger_blocks_cash(snapshot):
    row = {'id': 10, 'type': 'CASH_TRANSACTION', 'description': 'Flatex Interest Income',
        'change': 1, 'currency': 'EUR', 'date': '2026-01-01T00:00:00Z',
        'valueDate': '2026-01-01T00:00:00Z'}
    snapshot['cash_movements'].append(row)
    with pytest.raises(RuntimeError, match='blocks account writes'):
        extract(snapshot)
    row['description'] = 'Unknown'
    with pytest.raises(RuntimeError, match='Unknown'):
        extract(snapshot)


def test_clean_evidence_invokes_writer_once(snapshot):
    calls = []
    def put(account, balance):
        calls.append((account, balance))
        return True
    assert adapter.apply_cash_balance(snapshot, TARGET, '123', put,
        dry_run=False, import_ok=True, now=NOW) == 12.3
    assert calls == [('target-a', 12.3)]


def test_default_dry_run_does_not_invoke_writer(snapshot):
    def forbidden(*args):
        pytest.fail('DRY_RUN attempted PUT')
    assert adapter.apply_cash_balance(snapshot, TARGET, '123', forbidden,
        import_ok=True, now=NOW) == 12.3


@pytest.mark.parametrize('kwargs', [{}, {'import_ok': False}, {'import_ok': None},
    {'import_ok': 1}, {'import_ok': True, 'uncertain': True},
    {'import_ok': True, 'uncertain': 'false'}, {'import_ok': True, 'dry_run': 'false'}])
def test_ambiguous_import_or_flags_never_invoke_writer(snapshot, kwargs):
    def forbidden(*args):
        pytest.fail('Ambiguous state attempted PUT')
    with pytest.raises(RuntimeError, match='blocks cash update'):
        adapter.apply_cash_balance(snapshot, TARGET, '123', forbidden, now=NOW, **kwargs)


def test_invalid_cash_never_invokes_writer(snapshot):
    def forbidden(*args):
        pytest.fail('Invalid cash attempted PUT')
    set_total(snapshot, 'totalCash', None)
    with pytest.raises(RuntimeError):
        adapter.apply_cash_balance(snapshot, TARGET, '123', forbidden,
            dry_run=False, import_ok=True, now=NOW)


@pytest.mark.parametrize('result', [False, None, 1, {}])
def test_unconfirmed_writer_result_fails(snapshot, result):
    with pytest.raises(RuntimeError, match='confirm success'):
        adapter.apply_cash_balance(snapshot, TARGET, '123', lambda *args: result,
            dry_run=False, import_ok=True, now=NOW)
