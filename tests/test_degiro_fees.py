"""Synthetic standalone fees and evidence that execution costs are not repeated."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter
import ghostfolio_core as core


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['account_info'] = {'baseCurrency': 'EUR'}
    data['cash_movements'] = [data['cash_movements'][name]
        for name in ('trade_commission', 'exchange_connection_fee')]
    for row in data['cash_movements']:
        row['valueDate'] = row['date']
    return data


def normalize(snapshot):
    return adapter.normalize_fees(snapshot, 'target-a')


def test_only_connection_charge_is_a_standalone_fee(snapshot):
    assert normalize(snapshot) == [{'accountId': 'target-a', 'comment': 'DEGIRO#123:FEE:104',
        'currency': 'EUR', 'dataSource': 'MANUAL', 'date': '2025-12-31T23:00:00+00:00',
        'fee': 2.5, 'quantity': 1, 'symbol': 'GF_DEGIRO_123_EXCHANGE_CONNECTION_EUR',
        'type': 'FEE', 'unitPrice': 0}]


def test_commission_and_autofx_are_already_execution_costs(snapshot):
    snapshot['cash_movements'].pop()
    assert normalize(snapshot) == []
    trade = adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'USD'})[0]
    assert trade['fee'] == pytest.approx(.165)


def test_overlap_is_deduplicated_but_separate_fee_rows_remain(snapshot):
    duplicate = deepcopy(snapshot['cash_movements'][1])
    duplicate['balance'] = 100
    snapshot['cash_movements'].append(duplicate)
    assert len(normalize(snapshot)) == 1
    duplicate['id'] = 204
    assert [a['comment'] for a in normalize(snapshot)] == ['DEGIRO#123:FEE:104', 'DEGIRO#123:FEE:204']


def test_changed_fee_identity_blocks(snapshot):
    duplicate = deepcopy(snapshot['cash_movements'][1])
    duplicate['change'] = -3
    snapshot['cash_movements'].append(duplicate)
    with pytest.raises(RuntimeError, match='Conflicting'):
        normalize(snapshot)


@pytest.mark.parametrize('field,value', [('change', 2.5), ('change', 0), ('change', None),
    ('change', float('nan')), ('change', -.001), ('currency', 'USD'), ('currency', 'GBp'),
    ('productId', 20), ('orderId', 'refund-reference'), ('date', '2026-01-01'),
    ('valueDate', None), ('description', 'Frais de connexion remboursement'), ('id', True)])
def test_unverified_fee_sign_relation_and_units_block(snapshot, field, value):
    snapshot['cash_movements'][1][field] = value
    with pytest.raises(RuntimeError):
        normalize(snapshot)


@pytest.mark.parametrize('field,value', [('change', -.15), ('currency', 'USD'),
    ('productId', 21), ('date', '2026-01-04T00:00:00Z'), ('orderId', None)])
def test_orphan_or_mismatched_commission_blocks(snapshot, field, value):
    snapshot['cash_movements'][0][field] = value
    with pytest.raises(RuntimeError):
        normalize(snapshot)


def test_multiple_execution_candidates_are_ambiguous(snapshot):
    second = deepcopy(snapshot['transactions'][0])
    second['id'] = 11
    snapshot['transactions'].append(second)
    with pytest.raises(RuntimeError, match='ambiguous'):
        normalize(snapshot)


def test_two_commissions_cannot_evidence_one_execution(snapshot):
    second = deepcopy(snapshot['cash_movements'][0])
    second['id'] = 203
    snapshot['cash_movements'].append(second)
    with pytest.raises(RuntimeError, match='does not reconcile'):
        normalize(snapshot)


@pytest.mark.parametrize('field,value', [('feeInBaseCurrency', .05),
    ('autoFxFeeInBaseCurrency', .10), ('totalFeesInBaseCurrency', -.05),
    ('orderId', 'different-order')])
def test_inconsistent_execution_costs_block(snapshot, field, value):
    snapshot['transactions'][0][field] = value
    with pytest.raises(RuntimeError, match='does not reconcile'):
        normalize(snapshot)


@pytest.mark.parametrize('name', ['flatex_interest', 'monetary_fund_compensation'])
def test_unsupported_cash_blocks_even_valid_fees(snapshot, name):
    rows = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())['cash_movements']
    row = rows[name]
    row['valueDate'] = row['date']
    row['change'] = -1
    snapshot['cash_movements'].append(row)
    with pytest.raises(RuntimeError):
        normalize(snapshot)


def test_cash_only_fx_does_not_become_a_fee(snapshot):
    for identity, description, amount in [(301, 'Opération de change - Débit', -10),
                                         (302, 'Operation de change - Crédit', 11)]:
        snapshot['cash_movements'].append({'id': identity, 'type': 'CASH_TRANSACTION',
            'description': description, 'change': amount, 'currency': 'EUR',
            'date': '2026-01-02T00:00:00Z', 'valueDate': '2026-01-02T00:00:00Z'})
    assert len(normalize(snapshot)) == 1


def test_source_identity_and_target_are_scoped(snapshot):
    first = normalize(snapshot)[0]
    snapshot['source_account'] = '456'
    second = adapter.normalize_fees(snapshot, 'target-b')[0]
    assert second['comment'] == 'DEGIRO#456:FEE:104'
    assert first['symbol'] != second['symbol']
    assert first['accountId'] != second['accountId']


@pytest.mark.parametrize('target', [None, '', ' '])
def test_missing_target_blocks(snapshot, target):
    with pytest.raises(RuntimeError, match='target account'):
        adapter.normalize_fees(snapshot, target)


def accepted_row(activity):
    row = {**activity, 'id': 'created-fee', 'assetProfile': {
        'symbol': activity['symbol'], 'dataSource': 'MANUAL', 'isActive': True}}
    row.pop('symbol')
    row.pop('dataSource')
    return row


def test_core_accepts_exact_returned_fee_evidence(snapshot):
    activities = normalize(snapshot)
    assert core.accepted_import_subset(activities, {'activities': [accepted_row(activities[0])]}) == activities
    assert core.accepted_import_subset(activities, {'activities': []}) == []


@pytest.mark.parametrize('field,value', [('fee', 0), ('fee', True), ('quantity', 2),
    ('unitPrice', 2.5), ('currency', 'USD'), ('type', 'INTEREST'),
    ('date', '2026-01-01T00:00:00Z'), ('comment', 'DEGIRO#123:FEE:999'),
    ('accountId', 'target-b'), ('id', None), ('error', {'code': 'IS_DUPLICATE'})])
def test_core_rejects_missing_or_changed_returned_evidence(snapshot, field, value):
    activities = normalize(snapshot)
    row = accepted_row(activities[0])
    row[field] = value
    with pytest.raises(RuntimeError):
        core.accepted_import_subset(activities, {'activities': [row]})


def test_returned_data_source_must_match_manual_fee(snapshot):
    activities = normalize(snapshot)
    row = accepted_row(activities[0])
    row['assetProfile']['dataSource'] = 'YAHOO'
    with pytest.raises(RuntimeError):
        core.accepted_import_subset(activities, {'activities': [row]})
