"""Observed synthetic cash taxonomy and conservative dividend associations."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['cash_movements'] = [data['cash_movements'][name] for name in ('paid_dividend', 'dividend_withholding')]
    return data


def normalize(snapshot):
    return adapter.normalize_dividends(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'USD'})


def test_gross_payment_and_same_currency_withholding(snapshot):
    activity, = normalize(snapshot)
    assert activity == {'accountId': 'target-a', 'comment': 'DEGIRO#123:DIVIDEND:101',
        'currency': 'USD', 'dataSource': 'YAHOO', 'date': '2026-01-03T09:00:00+00:00',
        'fee': 1.5, 'quantity': 1, 'symbol': 'TEST', 'type': 'DIVIDEND', 'unitPrice': 10.}


def test_partial_sales_and_upcoming_payments_do_not_change_paid_amount(snapshot):
    expected = normalize(snapshot)
    snapshot.update(transactions=[{'buysell': 'S', 'quantity': -.5}],
        upcoming_payments=[{'change': 99999}], update={'portfolio': {'value': []}})
    assert normalize(snapshot) == expected


def test_same_day_distinct_payment_times_remain_distinct(snapshot):
    second = deepcopy(snapshot['cash_movements'])
    for row in second:
        row['id'] += 100
        row['date'] = '2026-01-03T11:00:00+01:00'
    snapshot['cash_movements'].extend(second)
    activities = normalize(snapshot)
    assert [a['comment'] for a in activities] == ['DEGIRO#123:DIVIDEND:101', 'DEGIRO#123:DIVIDEND:201']
    assert [a['unitPrice'] for a in activities] == [10, 10]


def test_exact_payment_time_and_value_date_are_required(snapshot):
    for field in ('date', 'valueDate'):
        changed = deepcopy(snapshot)
        changed['cash_movements'][1][field] = '2026-01-04T10:00:00+01:00'
        with pytest.raises(RuntimeError, match='withholding'):
            normalize(changed)


def test_utc_shift_preserves_payment_instant(snapshot):
    for row in snapshot['cash_movements']:
        row['date'] = '2026-01-03T00:15:00+01:00'
    assert normalize(snapshot)[0]['date'] == '2026-01-02T23:15:00+00:00'


def test_overlap_ignores_only_derived_balance(snapshot):
    expected = normalize(snapshot)
    duplicate = deepcopy(snapshot['cash_movements'][0])
    duplicate['balance'] = 123
    snapshot['cash_movements'].append(duplicate)
    assert normalize(snapshot) == expected
    duplicate['change'] = 11
    with pytest.raises(RuntimeError, match='Conflicting'):
        normalize(snapshot)


@pytest.mark.parametrize('category_index', [0, 1])
def test_multiple_candidates_same_exact_group_block(snapshot, category_index):
    other = deepcopy(snapshot['cash_movements'][category_index])
    other['id'] += 100
    snapshot['cash_movements'].append(other)
    with pytest.raises(RuntimeError, match='Ambiguous'):
        normalize(snapshot)


@pytest.mark.parametrize('keep', [[0], [1], []])
def test_orphan_or_untaxed_payment_is_unverified(snapshot, keep):
    snapshot['cash_movements'] = [snapshot['cash_movements'][i] for i in keep]
    if keep:
        with pytest.raises(RuntimeError, match='unverified'):
            normalize(snapshot)
    else:
        assert normalize(snapshot) == []


@pytest.mark.parametrize('index,field,value', [
    (0, 'change', -10), (1, 'change', 1.5), (0, 'change', 0), (1, 'change', 0),
    (0, 'change', None), (1, 'change', float('nan')), (0, 'currency', 'GBp'),
    (1, 'currency', 'EUR'), (0, 'date', '2026-01-03'), (1, 'valueDate', None),
    (0, 'productId', None), (1, 'productId', 21), (0, 'id', None),
    (0, 'orderId', 'new-reference'), (0, 'description', 'Dividend'),
    (0, 'description', 'Dividende annulation'), (1, 'change', -11),
    (0, 'type', 'UNKNOWN'), (0, 'description', None),
])
def test_unsupported_cash_or_association_blocks(snapshot, index, field, value):
    snapshot['cash_movements'][index][field] = value
    with pytest.raises(RuntimeError):
        normalize(snapshot)


@pytest.mark.parametrize('name', ['flatex_interest', 'monetary_fund_compensation'])
def test_known_unsupported_category_blocks_entire_account(snapshot, name):
    all_rows = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())['cash_movements']
    row = all_rows[name]
    row['valueDate'] = row['date']
    row['change'] = -1
    snapshot['cash_movements'].append(row)
    with pytest.raises(RuntimeError):
        normalize(snapshot)


def test_all_observed_categories_have_explicit_owners(snapshot):
    rules = adapter.load_cash_rules()
    rows = []
    descriptions = {'exchange_connection_fee': 'Frais de connexion aux places boursières 2026 (TEST)',
        'bank_withdrawal': 'Retrait TEST', 'cash_sweep_annotation': 'Virement TEST', 'executed_trade_cash': 'Achat TEST'}
    for index, (name, rule) in enumerate(rules.items(), start=1):
        rows.append({'id': index, 'type': rule['type'],
            'description': rule.get('description_exact', descriptions.get(name)),
            'date': '2026-01-03T10:00:00+01:00', 'valueDate': '2026-01-03T00:00:00+01:00',
            'currency': 'EUR', 'productId': 20, 'orderId': 'synthetic-order',
            'change': None if rule.get('treatment') == 'nonfinancial_notice' else (-1 if rule.get('sign') == 'negative' else 1)})
    for row in rows:
        if row['description'] in ('Flatex Interest Income', 'Compensation Fonds Monétaires DEGIRO'):
            row.pop('productId')
            row.pop('orderId')
        if row['description'] == 'Flatex Interest Income':
            row['change'] = 0
    classified = adapter.classify_cash_movements(rows)
    assert set(classified) == set(rules)
    assert all(len(values) == 1 for values in classified.values())
    rows[-1]['description'] = 'UNRECOGNIZED-PRIVATE-LABEL'
    with pytest.raises(RuntimeError) as error:
        adapter.classify_cash_movements(rows)
    assert 'PRIVATE' not in str(error.value)


def test_ambiguous_rules_never_select_first_match(snapshot):
    rules = adapter.load_cash_rules()
    rules['duplicate'] = deepcopy(rules['paid_dividend'])
    with pytest.raises(RuntimeError, match='ambiguous'):
        adapter.classify_cash_movements(snapshot['cash_movements'], rules)


def test_financial_notice_is_not_silently_ignored():
    row = {'id': 1, 'date': '2026-01-01T00:00:00Z', 'type': 'FLATEX_CASH_SWEEP',
           'description': 'Virement TEST', 'change': 1}
    with pytest.raises(RuntimeError, match='unexpectedly contains'):
        adapter.classify_cash_movements([row])
    row['change'] = None
    assert adapter.classify_cash_movements([row])['cash_sweep_annotation'] == [row]


@pytest.mark.parametrize('field,value', [('currency', 'EUR'), ('productType', 'ETF'),
    ('contractSize', 100), ('id', '21'), ('isin', 'US0378331006')])
def test_unverified_dividend_product_blocks(snapshot, field, value):
    snapshot['products']['20'][field] = value
    with pytest.raises(RuntimeError):
        normalize(snapshot)


def test_missing_mapping_or_quote_currency_blocks(snapshot):
    with pytest.raises(RuntimeError, match='mapping'):
        adapter.normalize_dividends(snapshot, 'target-a', {}, {'TEST': 'USD'})
    with pytest.raises(RuntimeError, match='quote units'):
        adapter.normalize_dividends(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'EUR'})


def test_source_and_target_account_identity_is_stable(snapshot):
    first = normalize(snapshot)[0]
    snapshot['source_account'] = '456'
    second = normalize(snapshot)[0]
    assert first['comment'] != second['comment']
    third = adapter.normalize_dividends(snapshot, 'target-b', {'US0378331005': 'TEST'}, {'TEST': 'USD'})[0]
    assert second['accountId'] != third['accountId']


@pytest.mark.parametrize('document', [None, {}, {'format': 2, 'rules': {}},
    {'format': 1, 'rules': {'bad': {'type': 'CASH_TRANSACTION'}}},
    {'format': 1, 'rules': {'bad': {'type': 'CASH_TRANSACTION', 'description_pattern': '.*'}}},
    {'format': 1, 'rules': {'bad': {'type': 'CASH_TRANSACTION', 'description_pattern': '^[$'}}},
    {'format': 1, 'rules': {'bad': {'type': 'CASH_TRANSACTION', 'description_exact': 'X', 'sign': 'ANY'}}},
    {'format': 1, 'rules': {'bad': {'type': 'CASH_TRANSACTION', 'description_exact': 'X', 'product_required': 'true'}}},
])
def test_invalid_rule_file_fails_closed(tmp_path, document):
    path = tmp_path / 'rules.yaml'
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(RuntimeError, match='Invalid DEGIRO cash rules'):
        adapter.load_cash_rules(path)


def test_zero_interest_does_not_block_dividend_conversion(snapshot):
    snapshot['cash_movements'].append({'id': 500, 'type': 'CASH_TRANSACTION',
        'description': 'Flatex Interest Income', 'change': 0, 'currency': 'EUR',
        'date': '2026-01-01T00:00:00Z', 'valueDate': '2026-01-01T00:00:00Z'})
    assert len(normalize(snapshot)) == 1


def test_sweep_statement_annotation_has_no_amount():
    row = {'id': 501, 'type': 'FLATEX_CASH_SWEEP', 'description': 'Virement TEST',
           'date': '2026-01-01T00:00:00Z', 'change': None}
    assert adapter.classify_cash_movements([row])['cash_sweep_annotation'] == [row]
    row['change'] = 1
    with pytest.raises(RuntimeError, match='unexpectedly contains'):
        adapter.classify_cash_movements([row])
