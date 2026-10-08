"""Compare unchanged pinned V3 output with broker API normalization offline."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter
from test_degiro_sync import NOW, TARGET, MAPPING, QUOTES, activity_row, opening_holding, snapshot


@pytest.fixture
def conversion():
    return yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_v3_transition.yaml').read_text())


def test_native_v3_foreign_commission_is_not_adapter_fee_evidence(conversion, snapshot):
    generated, = conversion['cases']['foreign_fee']['output']['activities']
    trade, = adapter.normalize_trades(snapshot, TARGET['id'], MAPPING, QUOTES)
    assert generated['currency'] == trade['currency'] == 'USD'
    assert generated['quantity'] == trade['quantity'] == 2
    assert generated['unitPrice'] == trade['unitPrice'] == 10
    # Broker API explicitly supplies EUR fee and gross USD/EUR rate 1.1.
    assert Decimal(str(trade['fee'])) == Decimal('0.165')
    assert Decimal(str(generated['fee'])) == Decimal('0.15')
    generated['accountId'] = TARGET['id']
    rows, _ = adapter.existing_activity_context(
        {'activities': [opening_holding(), activity_row(generated, 'csv-trade')], 'count': 2}, TARGET)
    with pytest.raises(RuntimeError, match='Manual or CSV'):
        adapter.pending_activities([trade], rows, TARGET, snapshot['source_account'])


def test_api_preserves_payment_omitted_by_native_v3_same_day_dedup(conversion, snapshot):
    snapshot['cash_movements'] = [r for r in snapshot['cash_movements'] if r['id'] in (101, 102)]
    second = deepcopy(snapshot['cash_movements'])
    for row in second:
        row['id'] += 100
        row['date'] = '2026-01-03T14:00:00+01:00'
        row['change'] *= 2
    snapshot['cash_movements'].extend(second)
    candidates = adapter.normalize_dividends(snapshot, TARGET['id'], MAPPING, QUOTES)
    generated, = conversion['cases']['same_day_payments']['output']['activities']
    assert [a['unitPrice'] for a in candidates] == [10, 20]
    assert [a['fee'] for a in candidates] == [1.5, 3]
    assert len({a['comment'] for a in candidates}) == 2
    assert generated['unitPrice'] == 10 and generated['fee'] == 1.5
    generated['accountId'] = TARGET['id']
    rows, _ = adapter.existing_activity_context(
        {'activities': [activity_row(generated, 'csv-dividend')], 'count': 1}, TARGET)
    with pytest.raises(RuntimeError, match='Manual or CSV'):
        adapter.pending_activities(candidates, rows, TARGET, snapshot['source_account'])


def test_empty_v3_output_cannot_remove_whole_ledger_category_gate(conversion, snapshot):
    assert conversion['cases']['unsupported_categories']['output']['activities'] == []
    contract = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    snapshot['cash_movements'].extend(contract['cash_movements'][name]
        for name in ('flatex_interest', 'monetary_fund_compensation'))
    for row in snapshot['cash_movements']:
        row.setdefault('valueDate', row['date'])
    with pytest.raises(RuntimeError, match='Unsupported DEGIRO cash category'):
        adapter.normalize_dividends(snapshot, TARGET['id'], MAPPING, QUOTES)
    with pytest.raises(RuntimeError, match='Unsupported DEGIRO cash category'):
        adapter.current_cash_balance(snapshot, TARGET, snapshot['source_account'], now=NOW)
