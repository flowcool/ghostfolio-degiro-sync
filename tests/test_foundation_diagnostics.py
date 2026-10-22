"""Exact observational reconciliation; all numeric evidence is synthetic."""
from copy import deepcopy
from decimal import Decimal

from ghostfolio_degiro_sync import diagnostics
from test_foundation_identity import candidate
from test_degiro_sync import snapshot


def test_exact_comparison_retains_wire_decimals_and_zero_tolerance():
    expected = candidate()
    expected['unitPrice'] = Decimal('1.00000000000000001')
    observed = {**expected, 'unitPrice': Decimal('1.00000000000000002'), 'id': 'row-a'}
    before = deepcopy((expected, observed))
    report = diagnostics.reconcile_activities([expected], [observed], '2026-01-01', '2026-01-31')
    assert report[0]['status'] == 'to-check'
    assert report[0]['checks']['unitPrice'] == 'different'
    assert report[0]['target'] == 'row-a'
    assert (expected, observed) == before


def test_dividend_activity_quantity_is_not_security_quantity():
    expected = candidate('DIVIDEND', 'DIVIDEND')
    report = diagnostics.reconcile_activities([expected], [{**expected, 'id': 'row-a'}],
        '2026-01-01', '2026-01-31')
    assert report[0]['status'] == 'coherent'
    assert report[0]['security_quantity'] is None
    assert report[0]['expected']['quantity'] == 1


def test_complete_coverage_and_contention_are_explicit():
    first = candidate()
    second = {**first, 'comment': 'DEGIRO#v1#123:TRADE:10', 'id': 'duplicate'}
    old = {**first, 'comment': 'DEGIRO#123:TRADE:11', 'id': 'old', 'date': '2020-01-01T00:00:00Z'}
    manual = {**first, 'comment': None, 'id': 'manual'}
    report = diagnostics.reconcile_activities([first], [{**first, 'id': 'one'}, second, old, manual],
        '2026-01-01', '2026-01-31')
    assert [block['status'] for block in report] == ['uncertain', 'outside-window', 'informational']
    assert report[0]['observed_ids'] == ['one', 'duplicate']
    assert report[0]['target'] is None
    assert sum(len(block['observed_ids']) for block in report) == 4


def test_missing_exact_evidence_remains_uncertain_and_unsupported_units_unavailable():
    row = candidate()
    row['currency'] = 'GBp'
    report = diagnostics.reconcile_activities([row], [{**row, 'id': 'one'}], None, None, exact=False)
    assert report[0]['status'] == 'uncertain'
    assert report[0]['checks']['currency'] == 'unavailable'
    assert report[0]['security_quantity'] is None


def test_original_source_json_decimals_survive_conversion(snapshot):
    import json
    from test_degiro_sync import MAPPING, QUOTES
    raw = json.dumps({'data': snapshot['transactions']})
    # The extra digits collapse if decoded through a binary float.
    raw = raw.replace('"price": 10.0', '"price": 10.00000000000000001')
    if '10.00000000000000001' not in raw:
        raw = raw.replace('"price": 10', '"price": 10.00000000000000001')
    snapshot['_diagnostic_wire'] = [
        {'path': '/transactions', 'body': raw},
        {'path': '/accountoverview', 'body': json.dumps({'data': {'cashMovements': snapshot['cash_movements']}})},
        {'path': '/products/info', 'body': json.dumps({'data': snapshot['products']})}]
    activities = diagnostics.exact_source_activities(snapshot, 'target-a', MAPPING, QUOTES)
    assert activities is not None
    trade = next(row for row in activities if row['type'] == 'SELL')
    assert trade['unitPrice'] == Decimal('10.00000000000000001')


def test_split_source_history_does_not_claim_ownership_from_equal_amounts():
    row = candidate('DIVIDEND', 'DIVIDEND')
    source = [row, {**row, 'comment': 'DEGIRO#123:DIVIDEND:11'}]
    stored = [{**row, 'id': 'manual', 'comment': None, 'unitPrice': 4}]
    report = diagnostics.reconcile_activities(source, stored, '2026-01-01', '2026-01-31')
    assert sum(block['source_count'] for block in report) == 2
    assert sum(len(block['observed_ids']) for block in report) == 1
    assert all(block['target'] is None for block in report)


def test_report_is_observational_for_selection(snapshot):
    from ghostfolio_degiro_sync import sync
    from test_degiro_sync import MAPPING, NOW, QUOTES, TARGET, opening_holding
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': True}
    body = {'activities': [opening_holding()], 'count': 1}
    before = sync.select_account_activities(config, snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
    report = diagnostics.snapshot_reconciliation(snapshot, body, 'target-a', MAPPING, QUOTES)
    after = sync.select_account_activities(config, snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
    assert before == after
    assert report and all(not block['exact'] for block in report)
