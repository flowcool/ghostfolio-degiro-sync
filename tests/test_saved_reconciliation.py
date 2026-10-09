"""Synthetic evidence comparisons must preserve discrepancies and private inputs."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import csv
import json
import os
from pathlib import Path

import pytest

from scripts import reconcile_saved as report


def movement(amount='10.00'):
    return {'id': 10, 'type': 'CASH_TRANSACTION', 'description': 'Dividende',
        'date': '2026-01-02T10:00:15+01:00', 'valueDate': '2026-01-02T00:00:00+01:00',
        'currency': 'USD', 'change': amount, 'productId': 20}


def statement(*rows):
    stream = io.StringIO()
    csv.writer(stream).writerows([report.CSV_HEADER, *rows])
    return stream.getvalue()


def csv_row(amount='10,00'):
    return ['02-01-2026', '10:00', '02-01-2026', 'Synthetic', 'US0378331005',
        'Dividende', '', 'USD', amount, 'USD', '0,00', '']


PRODUCTS = {'20': {'isin': 'US0378331005'}}


def test_json_body_identity_preserves_decimal_precision_and_scalar_types():
    first = report.decode_json('{"change": 0.123456789012345678901}')
    second = report.decode_json('{"change": 0.123456789012345678902}')
    assert report.body_digest(first) != report.body_digest(second)
    assert report.body_digest(first) != report.body_digest({'change': '0.123456789012345678901'})
    assert report.number(first['change']) == Decimal('0.123456789012345678901')


def test_nonfinite_json_is_refused():
    with pytest.raises(RuntimeError):
        report.decode_json('{"change": NaN}')


def test_statement_match_preserves_same_minute_multiplicity():
    result = report.compare_statement([movement(), movement()], PRODUCTS, statement(csv_row()))
    assert result['exact_minute_multiset_matches'] == 1
    assert result['source_only_rows'] == 1
    assert result['identity_or_completeness_proved'] is False


def test_one_cent_candidate_is_a_discrepancy():
    result = report.compare_statement([movement('10.01')], PRODUCTS, statement(csv_row()))
    assert result['exact_minute_multiset_matches'] == 0
    assert result['source_only_rows'] == result['statement_only_rows'] == 1
    discrepancy, = result['source_discrepancies'].values()
    candidate, = discrepancy['csv_candidates']
    assert candidate['different_fields'] == ['amount']
    assert candidate['row']['amount'] == Decimal('10.00')


def test_description_only_continuation_is_retained_separately():
    annotation = [''] * 12
    annotation[5] = 'Continuation'
    result = report.compare_statement([movement()], PRODUCTS, statement(csv_row(), annotation))
    assert result['statement_rows'] == 2
    assert result['dated_statement_rows'] == 1
    assert result['statement_annotations']['3']['preceding_line'] == 2
    assert result['identity_or_completeness_proved'] is False


@pytest.mark.parametrize('row', [[], ['footer'], [''] * 12,
    ['', '', '', '', '', 'Annotation', '', 'EUR', '1', '', '', '']])
def test_uncharacterized_statement_shapes_are_refused(row):
    with pytest.raises(RuntimeError):
        report.statement_keys(statement(row))


@pytest.mark.parametrize('value', ['NaN', 'Infinity', True])
def test_nonfinancial_numbers_are_refused(value):
    with pytest.raises(RuntimeError):
        report.number(value)


def test_missing_product_and_naive_source_clock_are_refused():
    with pytest.raises(RuntimeError, match='product'):
        report.movement_key(movement(), {})
    row = movement()
    row['date'] = '2026-01-02T10:00:00'
    with pytest.raises(RuntimeError, match='timestamp'):
        report.movement_key(row, PRODUCTS)


def test_exact_decimal_tie_describes_rules_without_proving_policy():
    source = {'products': {'20': {'currency': 'USD'}}, 'transactions': [
        {'id': 10, 'productId': 20, 'quantity': -3, 'price': '4.335', 'total': '13.005'}]}
    result = report.rounding_diagnostic(source)['10']
    assert result['signed_price_times_quantity'] == Decimal('13.005')
    assert result['half_even'] == Decimal('13.00')
    assert result['half_up'] == Decimal('13.01')
    assert result['broker_rounding_policy_proved'] is False


def test_same_day_financial_candidate_does_not_authorize_adoption():
    proposed = {'accountId': 'target', 'comment': 'DEGIRO#123:DIVIDEND:10', 'symbol': 'TEST',
        'type': 'DIVIDEND', 'dataSource': 'YAHOO', 'currency': 'USD',
        'date': '2026-01-02T09:00:15Z', 'quantity': 1, 'unitPrice': 10, 'fee': 1.5}
    existing = {**proposed, 'id': 'created', 'comment': None, 'date': '2026-01-02T10:00:00Z'}
    foreign = {**existing, 'id': 'foreign', 'accountId': 'other'}
    result = report.destination_candidates([proposed], [existing, foreign], 'target')[proposed['comment']]
    assert list(result['candidates']) == ['created']
    assert result['candidates']['created']['different_fields'] == ['comment', 'date']
    assert result['candidates']['created']['source_minus_existing_seconds'] == '-3585.0'
    assert result['adoption_authorized'] is False


def test_raw_bodies_keep_provenance_and_unverified_windows(tmp_path):
    row = movement()
    paths = {}
    for index, body in enumerate([{'cashMovements': [row, deepcopy(row)]},
                                 {'cashMovements': [{**row, 'balance': {'total': 99}}]}, {}]):
        path = tmp_path / f'window-{index:03}.json'
        paths[path] = json.dumps({'capture': {'endpoint': 'accountoverview', 'http_status': 200,
            'dates': {'fromDate': ['01/01/2026'], 'toDate': ['02/01/2026']}}, 'body': {'data': body}})
    for path, content in paths.items():
        path.write_text(content)
    (tmp_path / 'window-summary.json').write_text('{}')
    result = report.archive_rows(tmp_path, lambda path: path.read_text())
    entry, = result['cash_bodies'].values()
    assert len(entry['occurrences']) == 3
    assert entry['occurrences'][1]['index'] == 1
    assert 'balance' not in entry['body']
    assert len(result['unverified_cash_windows']) == 1
    assert len(result['cash_identity_diagnostics']['repeated_bodies_within_response']) == 1


@pytest.mark.parametrize('status', [401, 500])
@pytest.mark.parametrize('endpoint', ['accountoverview', 'transactions'])
def test_unsuccessful_archived_response_is_refused(tmp_path, status, endpoint):
    rows = [movement()]
    body = {'data': {'cashMovements': rows} if endpoint == 'accountoverview' else rows}
    (tmp_path / 'window-000.json').write_text(json.dumps({'capture': {
        'endpoint': endpoint, 'http_status': status, 'dates': {}}, 'body': body}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='Unsuccessful archived response'):
        report.archive_rows(tmp_path, lambda path: path.read_text(encoding='utf-8'))


def test_conflicting_stable_ids_are_reported_without_collapsing_bodies():
    entries = {'a': {'body': movement('10'), 'occurrences': [{'path': 'first'}]},
        'b': {'body': movement('11'), 'occurrences': [{'path': 'second'}]}}
    result = report.identity_diagnostics(entries)
    assert result['conflicting_nonzero_ids'] == {'10': ['a', 'b']}
    assert len(entries) == 2


def test_report_cannot_overwrite_or_alias_evidence(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text('{}')
    hashes = {source: hashlib.sha256(source.read_bytes()).hexdigest()}
    with pytest.raises(RuntimeError, match='aliases'):
        report.publish({}, source, hashes)
    link = tmp_path / 'link.yaml'
    link.symlink_to(source)
    with pytest.raises(RuntimeError, match='aliases'):
        report.publish({}, link, hashes)
    output = tmp_path / 'report.yaml'
    report.publish({'amount': Decimal('1.005')}, output, hashes)
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert "1.005" in output.read_text()
    with pytest.raises(FileExistsError):
        report.publish({}, output, hashes)
    assert source.read_text() == '{}'


def test_changed_input_prevents_report_publication(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text('{}')
    hashes = {source: hashlib.sha256(source.read_bytes()).hexdigest()}
    source.write_text('{"changed": true}')
    output = tmp_path / 'report.yaml'
    with pytest.raises(RuntimeError, match='changed'):
        report.publish({}, output, hashes)
    assert not output.exists()


def test_private_report_cannot_be_published_under_tracked_project_path():
    output = Path(report.adapter.__file__).parent / 'public-report.yaml'
    with pytest.raises(RuntimeError, match='Private snapshot'):
        report.publish({}, output, {})
    assert not output.exists()


def test_saved_replay_fails_if_adapter_attempts_dispatch(monkeypatch):
    monkeypatch.setattr(report.adapter, 'existing_activity_context', lambda *args: ([], {}))
    for name in ('normalize_trades', 'normalize_dividends', 'normalize_fees', 'normalize_cash_yield'):
        monkeypatch.setattr(report.adapter, name, lambda *args: [])

    def dispatch(config, source, target, existing, mapping, quotes, importer, cash, now=None):
        importer([])

    monkeypatch.setattr(report.adapter, 'synchronize_account', dispatch)
    with pytest.raises(AssertionError, match='Financial dispatch forbidden'):
        report.replay({'source_account': '123', 'fetched_at': '2026-01-02T10:00:00Z'},
            {'activities': {}}, {}, {'id': 'target'})
