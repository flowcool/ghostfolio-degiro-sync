"""Synthetic financial regressions; never consult live accounts or providers."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['account_info'] = {'baseCurrency': data['base_currency']}
    return data


def convert(snapshot):
    return adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'USD'})


def buy(snapshot, execution_id=11, quantity='2'):
    row = deepcopy(snapshot['transactions'][0])
    row.update(id=execution_id, buysell='B', quantity=quantity, total='-20',
               totalInBaseCurrency='-18.18')
    return row


def test_cross_currency_sell_preserves_cost_and_identity(snapshot):
    activity, = convert(snapshot)
    assert activity == {'accountId': 'target-a', 'comment': 'DEGIRO#123:TRADE:10',
        'currency': 'USD', 'dataSource': 'YAHOO', 'date': '2026-01-02T09:00:00+00:00',
        'fee': .165, 'quantity': 2., 'symbol': 'TEST', 'type': 'SELL', 'unitPrice': 10.}
    # Total already includes AutoFX; nettFxRate must never apply it again.
    snapshot['transactions'][0]['nettFxRate'] = 99
    assert convert(snapshot) == [activity]


def test_fractional_buy_and_same_currency(snapshot):
    snapshot['products']['20']['currency'] = 'EUR'
    row = buy(snapshot, quantity='0.125')
    row.update(price='10.32', total='-1.29', totalInBaseCurrency='-1.29',
               fxRate=1, grossFxRate=1, autoFxFeeInBaseCurrency=0,
               totalFeesInBaseCurrency='-0.05')
    snapshot['transactions'] = [row]
    activity, = adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'EUR'})
    assert activity['quantity'] == .125
    assert activity['unitPrice'] == 10.32
    assert activity['fee'] == .05
    assert activity['type'] == 'BUY'


def test_jpy_total_rounding_and_fee_conversion(snapshot):
    snapshot['products']['20']['currency'] = 'JPY'
    snapshot['transactions'][0].update(quantity=-.5, price='1001', total=501,
        totalInBaseCurrency='3.34', fxRate=150, grossFxRate=150)
    activity, = adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'JPY'})
    assert activity['fee'] == 22.5
    assert activity['quantity'] == .5
    snapshot['transactions'][0]['total'] = 502
    with pytest.raises(RuntimeError, match='price and quantity'):
        adapter.normalize_trades(snapshot, 'target-a', {'US0378331005': 'TEST'}, {'TEST': 'JPY'})


@pytest.mark.parametrize('field,value', [
    ('buysell', 'BUY'), ('buysell', 'SELL'), ('buysell', ''), ('buysell', None),
    ('quantity', 2), ('quantity', 0), ('price', -10), ('price', 0), ('total', -20),
    ('totalInBaseCurrency', -18.18), ('total', 21), ('fxRate', 0), ('fxRate', -1),
    ('fxRate', 1 / 1.1), ('grossFxRate', 1.12), ('totalInBaseCurrency', 19),
    ('feeInBaseCurrency', .05), ('autoFxFeeInBaseCurrency', .10),
    ('totalFeesInBaseCurrency', -.05), ('totalFeesInBaseCurrency', .15),
    ('totalFeesInBaseCurrency', None), ('quantity', True), ('price', 'NaN'),
    ('quantity', float('inf')), ('feeInBaseCurrency', '-Infinity'),
    ('totalPlusFeeInBaseCurrency', 19), ('totalPlusAllFeesInBaseCurrency', 19),
    ('transfered', True), ('transfered', 'false'),
    ('id', None), ('id', True), ('id', '010'), ('id', '10:TRADE:11'),
    ('productId', '20.0'), ('date', '2026-01-02T10:00:00'), ('date', 'invalid'),
])
def test_invalid_financial_contract_is_blocked(snapshot, field, value):
    snapshot['transactions'][0][field] = value
    with pytest.raises(RuntimeError):
        convert(snapshot)


@pytest.mark.parametrize('field,value', [
    ('id', '21'), ('contractSize', 100), ('contractSize', None), ('productType', 'OPTION'),
    ('productType', 'ETF'), ('isin', 'US0378331006'), ('isin', None),
    ('currency', 'GBp'), ('currency', 'GBP'), ('currency', 'XXX'),
])
def test_unverified_metadata_is_blocked(snapshot, field, value):
    snapshot['products']['20'][field] = value
    with pytest.raises(RuntimeError):
        convert(snapshot)


@pytest.mark.parametrize('mapping,quotes', [({}, {'TEST': 'USD'}),
    ({'US0378331005': ''}, {'TEST': 'USD'}), ({'US0378331005': ' TEST'}, {'TEST': 'USD'}),
    ({'US0378331005': 'TEST'}, {}), ({'US0378331005': 'TEST'}, {'TEST': 'EUR'}),
    ({'US0378331005': 'TEST'}, {'TEST': 'GBp'})])
def test_no_ticker_fallback_or_quote_unit_guess(snapshot, mapping, quotes):
    with pytest.raises(RuntimeError):
        adapter.normalize_trades(snapshot, 'target-a', mapping, quotes)


def test_signed_buy_requires_matching_totals(snapshot):
    row = buy(snapshot)
    snapshot['transactions'] = [row]
    assert convert(snapshot)[0]['type'] == 'BUY'
    for field in ('quantity', 'total', 'totalInBaseCurrency'):
        broken = deepcopy(snapshot)
        broken['transactions'][0][field] = -Decimal(str(row[field]))
        with pytest.raises(RuntimeError):
            convert(broken)


def test_optional_net_totals_checked(snapshot):
    snapshot['transactions'][0].update(totalPlusFeeInBaseCurrency='18.13',
                                       totalPlusAllFeesInBaseCurrency='18.03')
    assert convert(snapshot)[0]['fee'] == .165


def test_timezone_day_shift_and_dst_are_preserved(snapshot):
    row = snapshot['transactions'][0]
    row['date'] = '2026-01-02T00:15:00+01:00'
    assert convert(snapshot)[0]['date'] == '2026-01-01T23:15:00+00:00'
    row['date'] = '2026-07-02T00:15:00+02:00'
    assert convert(snapshot)[0]['date'] == '2026-07-01T22:15:00+00:00'


def test_equal_overlap_kept_once_but_individual_fills_remain(snapshot):
    snapshot['transactions'].append(deepcopy(snapshot['transactions'][0]))
    assert len(convert(snapshot)) == 1
    second = deepcopy(snapshot['transactions'][0])
    second['id'] = 11
    snapshot['transactions'].append(second)
    assert len(convert(snapshot)) == 2
    snapshot['transactions'][1]['price'] = 9
    with pytest.raises(RuntimeError, match='Conflicting'):
        convert(snapshot)


def test_identity_scoped_by_source_and_target(snapshot):
    first = convert(snapshot)[0]
    snapshot['source_account'] = '456'
    second = convert(snapshot)[0]
    assert first['comment'] != second['comment']
    assert adapter.reconcile_trade_holdings([second], [first], {('target-a', 'TEST'): 2}) == [second]
    first['accountId'] = 'target-b'
    second['comment'] = first['comment']
    assert adapter.reconcile_trade_holdings([second], [first], {('target-a', 'TEST'): 2}) == [second]


def test_imported_execution_not_subtracted_again(snapshot):
    activity = convert(snapshot)[0]
    existing = dict(activity, id='server-id', date='2026-01-02T10:00:00+01:00')
    assert adapter.reconcile_trade_holdings([activity], [existing], {}) == []
    assert adapter.reconcile_trade_holdings([activity, activity], [], {('target-a', 'TEST'): 2}) == [activity]


@pytest.mark.parametrize('field,value', [('fee', .1), ('quantity', 1), ('unitPrice', 9),
    ('symbol', 'OTHER'), ('currency', 'EUR'), ('type', 'BUY'), ('date', '2026-01-03T09:00:00Z')])
def test_existing_identity_cannot_hide_changed_trade(snapshot, field, value):
    activity = convert(snapshot)[0]
    existing = dict(activity, **{field: value})
    with pytest.raises(RuntimeError, match='changed financial content'):
        adapter.reconcile_trade_holdings([activity], [existing], {('target-a', 'TEST'): 2})


def test_duplicate_existing_identity_blocks(snapshot):
    activity = convert(snapshot)[0]
    with pytest.raises(RuntimeError, match='Duplicate existing'):
        adapter.reconcile_trade_holdings([activity], [activity, activity], {})
    conflict = dict(activity, quantity=1)
    with pytest.raises(RuntimeError, match='Conflicting existing'):
        adapter.reconcile_trade_holdings([activity], [activity, conflict], {})
    with pytest.raises(RuntimeError, match='Conflicting pending'):
        adapter.reconcile_trade_holdings([activity, conflict], [], {('target-a', 'TEST'): 10})


def test_holdings_require_same_account_and_symbol(snapshot):
    activity = convert(snapshot)[0]
    for holdings in ({}, {('target-b', 'TEST'): 2}, {('target-a', 'OTHER'): 2}, {('target-a', 'TEST'): 1.9999}):
        with pytest.raises(RuntimeError, match='negative target holding'):
            adapter.reconcile_trade_holdings([activity], [], holdings)
    assert adapter.reconcile_trade_holdings([activity], [], {('target-a', 'TEST'): 2}) == [activity]


def test_chronology_and_fractional_position_guard(snapshot):
    sell = convert(snapshot)[0]
    purchase = dict(sell, comment='DEGIRO#123:TRADE:11', type='BUY', quantity=2,
                    date='2026-01-01T09:00:00+00:00')
    assert adapter.reconcile_trade_holdings([sell, purchase], [], {}) == [purchase, sell]
    purchase['date'] = '2026-01-03T09:00:00+00:00'
    with pytest.raises(RuntimeError, match='negative'):
        adapter.reconcile_trade_holdings([purchase, sell], [], {})
    sell['quantity'] = .125
    assert adapter.reconcile_trade_holdings([sell], [], {('target-a', 'TEST'): .125}) == [sell]


def test_manual_overlap_blocks_without_silent_identity_adoption(snapshot):
    activity = convert(snapshot)[0]
    manual = dict(activity, comment=None)
    for quantity in (2, 4):
        manual['quantity'] = quantity
        with pytest.raises(RuntimeError, match='explicit reconciliation'):
            adapter.reconcile_trade_holdings([activity], [manual], {('target-a', 'TEST'): 10})
    manual['accountId'] = 'target-b'
    assert adapter.reconcile_trade_holdings([activity], [manual], {('target-a', 'TEST'): 2}) == [activity]


def test_financial_values_do_not_echo_private_data():
    with pytest.raises(RuntimeError) as error:
        adapter.financial_decimal('PRIVATE-NONNUMERIC')
    assert 'PRIVATE' not in str(error.value)


def test_dividend_identity_is_not_a_trade_identity(snapshot):
    activity = convert(snapshot)[0]
    dividend = dict(activity, comment='DEGIRO#123:DIVIDEND:101', type='DIVIDEND')
    assert adapter.reconcile_trade_holdings([activity], [dividend], {('target-a', 'TEST'): 2}) == [activity]


@pytest.mark.parametrize('field,value', [('quantity', -2), ('quantity', 0),
    ('unitPrice', -1), ('fee', -.1), ('type', 'OTHER'), ('dataSource', 'MANUAL')])
def test_holdings_reject_malformed_pending_activities(snapshot, field, value):
    activity = convert(snapshot)[0]
    activity[field] = value
    with pytest.raises(RuntimeError):
        adapter.reconcile_trade_holdings([activity], [], {('target-a', 'TEST'): 10})
