"""Exact observational reconciliation; all numeric evidence is synthetic."""
import re
from copy import deepcopy
from decimal import Decimal

import pytest

from ghostfolio_degiro_sync import diagnostics
from test_foundation_identity import candidate
from test_degiro_sync import snapshot


@pytest.mark.parametrize('error', [RuntimeError, KeyError, TypeError, ValueError])
def test_unavailable_source_normalization_remains_visible(snapshot, monkeypatch, error):
    from ghostfolio_degiro_sync import accounting
    from test_degiro_sync import MAPPING, QUOTES, opening_holding
    def unavailable(*args):
        raise error('SYNTHETIC-PRIVATE-SOURCE')
    monkeypatch.setattr(accounting, 'normalize_dividends', unavailable)
    body = {'activities': [opening_holding()], 'count': 1}
    before = deepcopy((snapshot, body))
    report = diagnostics.snapshot_reconciliation(snapshot, body, 'target-a', MAPPING, QUOTES)
    assert sum(len(block['observed_ids']) for block in report) == 1
    assert sum(block['source_count'] for block in report) == len(snapshot['transactions']) + len(snapshot['cash_movements'])
    assert all(not block['exact'] and block['target'] is None for block in report)
    assert report[-1]['status'] == 'uncertain'
    assert report[-1]['reason'] == 'Source normalization unavailable'
    text = diagnostics.render_reconciliation(report)
    assert 'SYNTHETIC-PRIVATE-SOURCE' not in text
    assert (snapshot, body) == before


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


def test_manual_uuid_profile_rewrite_is_coherent():
    expected = candidate('FEE', 'FEE')
    expected.update(dataSource='MANUAL', symbol='GF_DEGIRO_123_FEE_EUR')
    observed = {**expected, 'id': 'row-a', 'symbol': '00000000-0000-4000-8000-000000000001'}
    report = diagnostics.reconcile_activities([expected], [observed], '2026-01-01', '2026-01-31')
    assert report[0]['status'] == 'coherent'
    assert report[0]['checks']['symbol'] == 'equal'


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
    row['currency'] = 'XAU'
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


@pytest.mark.parametrize('raw_currency,profile_currency,status,currency_check,observed_currency', [
    (None, 'EUR', 'coherent', 'equal', 'EUR'),
    ('EUR', 'USD', 'coherent', 'equal', 'EUR'),
    ('USD', 'EUR', 'to-check', 'different', 'USD'),
    (None, None, 'uncertain', 'unavailable', None),
    (None, 'GBp', 'to-check', 'different', 'GBp'),
])
def test_native_report_inherits_exact_profile_currency_without_changing_evidence(
        snapshot, raw_currency, profile_currency, status, currency_check, observed_currency):
    import json
    from test_degiro_sync import MAPPING, QUOTES, activity_row
    snapshot['_diagnostic_wire'] = [
        {'path': '/transactions', 'body': json.dumps({'data': snapshot['transactions']})},
        {'path': '/accountoverview', 'body': json.dumps({'data': {'cashMovements': snapshot['cash_movements']}})},
        {'path': '/products/info', 'body': json.dumps({'data': snapshot['products']})}]
    expected = diagnostics.exact_source_activities(snapshot, 'target-a', MAPPING, QUOTES)
    proposal = next(row for row in expected if row['type'] == 'FEE')
    stored = activity_row({**proposal, 'currency': raw_currency, 'symbol': '00000000-0000-4000-8000-000000000001'})
    stored['assetProfile']['currency'] = profile_currency
    body = {'activities': [stored], 'count': 1}
    body['_diagnostic_wire'] = json.dumps(body, default=float)
    before = deepcopy((snapshot, body))
    findings = diagnostics.snapshot_reconciliation(snapshot, body, 'target-a', MAPPING, QUOTES)
    matched = next(block for block in findings if block['observed_ids'])
    assert matched['status'] == status
    assert matched['checks']['currency'] == currency_check
    assert matched['observed']['currency'] == observed_currency
    assert (snapshot, body) == before


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


def test_plain_report_has_exact_target_and_one_action():
    target = '54c98163-34fc-4e46-837e-257798962734'
    expected = candidate()
    observed = {**expected, 'id': target, 'unitPrice': 3}
    findings = diagnostics.reconcile_activities([expected], [observed], '2026-01-01', '2026-01-31')
    text = diagnostics.render_reconciliation(findings)
    assert 'DEGIRO reconciliation: nothing written' in text
    assert f'Compared activity: {target}' in text
    assert f'Action: Inspect activity {target}.' in text
    assert text.count('Action:') == 1
    assert 'unitPrice 2.00 USD' in text and 'unitPrice 3.00 USD' in text
    assert 'Security quantity: 1' in text
    from scripts.check_degiro_report import check_report
    assert check_report(text) == []
    assert check_report(text.replace(f'Action: Inspect activity {target}.', 'Action: Inspect activity wrong-row.'))
    for prefix in ('Expected:', 'Observed:'):
        for field in ('quantity', 'unitPrice', 'fee'):
            bad = '\n'.join(re.sub(r'(?<=; )' + field + r' \S+', field + ' 1e+2', line)
                if line.startswith(prefix) else line for line in text.splitlines())
            assert 'Exponent notation in report' in check_report(bad)
    assert 'Exponent notation in report' in check_report(text.replace('Security quantity: 1',
        'Security quantity: 1e+2'))


def test_no_dividend_report_and_unavailable_units_are_explicit():
    from scripts.check_degiro_report import check_report
    empty = diagnostics.render_reconciliation([])
    assert 'No source or destination events available.' in empty
    assert check_report(empty) == []
    row = candidate('DIVIDEND', 'DIVIDEND')
    row['currency'] = 'XAU'
    text = diagnostics.render_reconciliation(diagnostics.reconcile_activities([row], [], None, None, exact=False))
    assert 'Security quantity: unavailable' in text
    assert 'unitPrice unavailable' in text
    assert 'Action: Inspect evidence; no activity selected.' in text
    assert check_report(text) == []


def test_manual_matching_skips_foreign_rows_without_profile_symbol():
    from ghostfolio_degiro_sync.ghostfolio import match_manual_activity
    activity = {'accountId': 'target-a', 'type': 'BUY', 'symbol': 'AAPL',
                'date': '2026-01-01T00:00:00Z', 'quantity': 1}
    incomplete_foreign = {'accountId': 'other', 'type': 'BUY',
                          'date': '2026-01-01T00:00:00Z', 'quantity': 1}
    assert not match_manual_activity(activity, [incomplete_foreign])


def test_original_source_derived_quote_units_match_exact_dto(snapshot):
    import json
    from test_degiro_sync import MAPPING
    product = snapshot['products']['20']
    product['currency'] = 'GBP'
    for row in snapshot['cash_movements']:
        if row.get('currency') == 'USD':
            row['currency'] = 'GBP'
    snapshot['_diagnostic_wire'] = [
        {'path': '/transactions', 'body': json.dumps({'data': snapshot['transactions']})},
        {'path': '/accountoverview', 'body': json.dumps({'data': {'cashMovements': snapshot['cash_movements']}})},
        {'path': '/products/info', 'body': json.dumps({'data': snapshot['products']})}]
    activities = diagnostics.exact_source_activities(snapshot, 'target-a', MAPPING, {'TEST': 'GBp'})
    assert activities is not None
    trade = next(row for row in activities if row['type'] == 'SELL')
    assert trade['currency'] == 'GBp' and trade['unitPrice'] == Decimal('1000')
    assert trade['fee'] == Decimal('16.500')


def test_report_explains_profile_currency_without_changing_original(snapshot):
    from test_degiro_sync import MAPPING, QUOTES, opening_holding
    row = opening_holding()
    row['currency'] = None
    row['assetProfile']['currency'] = 'CAD'
    body = {'activities': [row], 'count': 1}
    before = deepcopy(body)
    report = diagnostics.snapshot_reconciliation(snapshot, body, 'target-a', MAPPING, QUOTES)
    text = diagnostics.render_reconciliation(report)
    assert 'raw unavailable; effective CAD; provenance assetProfile.currency' in text
    assert body == before
