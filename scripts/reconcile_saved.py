#!/usr/bin/env python3
"""Diagnose retained DEGIRO/CSV/Ghostfolio evidence offline; never authorize writes."""

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


FIELDS = ('date', 'minute', 'value_date', 'isin', 'description', 'currency', 'amount', 'order')
CSV_HEADER = ['Date', 'Heure', 'Date de', 'Produit', 'Code ISIN', 'Description',
              'FX', 'Mouvements', '', 'Solde', '', 'ID Ordre']


def decode_json(text):
    def invalid_constant(unused):
        raise RuntimeError('Non-finite JSON number')

    return json.loads(text, parse_float=Decimal, parse_constant=invalid_constant)


def body_digest(value):
    """Retain JSON types and decimal precision in diagnostic body identities."""
    def typed(item):
        if isinstance(item, Decimal):
            return ['decimal', str(item)]
        if isinstance(item, dict):
            return ['object', [[key, typed(val)] for key, val in sorted(item.items())]]
        if isinstance(item, list):
            return ['array', [typed(val) for val in item]]
        return ['scalar', item]

    return hashlib.sha256(json.dumps(typed(value), separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise RuntimeError('Invalid financial number')
    try:
        result = Decimal(str(value).replace(',', '.'))
    except InvalidOperation:
        raise RuntimeError('Invalid financial number') from None
    if not result.is_finite():
        raise RuntimeError('Invalid financial number')
    return result


def statement_keys(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != CSV_HEADER:
        raise RuntimeError('Uncharacterized statement header')
    result = []
    annotations = {}
    for line, row in enumerate(rows[1:], 2):
        if len(row) != 12:
            raise RuntimeError('Uncharacterized statement row or annotation')
        if not row[0] and row[5] and all(not value for i, value in enumerate(row) if i != 5):
            annotations[str(line)] = {'description': row[5], 'preceding_line': line - 1,
                'disposition': 'unresolved_description_continuation; not a separate cash event'}
            continue
        try:
            datetime.strptime(row[0], '%d-%m-%Y')
            datetime.strptime(row[1], '%H:%M')
            datetime.strptime(row[2], '%d-%m-%Y')
        except ValueError:
            raise RuntimeError('Uncharacterized statement date or annotation') from None
        result.append((row[0], row[1], row[2], row[4], row[5], row[7], number(row[8]), row[11]))
    return result, annotations


def movement_key(row, products):
    date = datetime.fromisoformat(row['date'])
    value_date = datetime.fromisoformat(row['valueDate'])
    if date.utcoffset() is None or value_date.utcoffset() is None:
        raise RuntimeError('Uncharacterized source timestamp')
    product_id = row.get('productId')
    if product_id is not None and str(product_id) not in products:
        raise RuntimeError('Missing source product')
    product = products.get(str(product_id), {})
    return (date.strftime('%d-%m-%Y'), date.strftime('%H:%M'), value_date.strftime('%d-%m-%Y'),
            product.get('isin', ''), row['description'],
            row.get('currency') if row.get('change') is not None else '',
            number(row.get('change')), str(row.get('orderId') or ''))


def compare_statement(movements, products, statement):
    """Preserve multiplicity; near rows are diagnostic candidates, never matches."""
    source = Counter(movement_key(row, products) for row in movements)
    keys, annotations = statement_keys(statement)
    csv_rows = Counter(keys)
    source_only, csv_only = source - csv_rows, csv_rows - source
    discrepancies = {}
    for index, (key, count) in enumerate(sorted(source_only.items(), key=str)):
        # Exact association columns; a unique candidate still proves no equivalence.
        candidates = [other for other in csv_only if other[:4] == key[:4] and other[7] == key[7]]
        discrepancies[str(index)] = {'source': dict(zip(FIELDS, key)), 'occurrences': count,
            'csv_candidates': [{'row': dict(zip(FIELDS, other)), 'occurrences': csv_only[other],
                'different_fields': [field for i, field in enumerate(FIELDS) if key[i] != other[i]]}
                for other in candidates]}
    return {'source_rows': sum(source.values()), 'statement_rows': sum(csv_rows.values()) + len(annotations),
        'dated_statement_rows': sum(csv_rows.values()), 'statement_annotations': annotations,
        'exact_minute_multiset_matches': sum((source & csv_rows).values()),
        'source_only_rows': sum(source_only.values()), 'statement_only_rows': sum(csv_only.values()),
        'source_discrepancies': discrepancies,
        'statement_only': {str(i): {'row': dict(zip(FIELDS, key)), 'occurrences': count}
                           for i, (key, count) in enumerate(sorted(csv_only.items(), key=str))},
        'identity_or_completeness_proved': False}


def instant(value):
    return datetime.fromisoformat(adapter.broker_instant(value))


def different_activity_fields(source, existing):
    result = []
    for field in ('comment', 'date', 'quantity', 'unitPrice', 'fee'):
        if field == 'date':
            same = instant(source[field]) == instant(existing[field])
        elif field in ('quantity', 'unitPrice', 'fee'):
            same = number(source[field]) == number(existing[field])
        else:
            same = source.get(field) == existing.get(field)
        if not same:
            result.append(field)
    return result


def destination_candidates(proposed, existing, target):
    result = {}
    for row in proposed:
        day = instant(row['date']).astimezone(ZoneInfo('Europe/Zurich')).date()
        candidates = [other for other in existing if other.get('accountId') == target
            and other['symbol'] == row['symbol'] and other['dataSource'] == row['dataSource']
            and other['type'] == row['type'] and other['currency'] == row['currency']
            and instant(other['date']).astimezone(ZoneInfo('Europe/Zurich')).date() == day]
        result[row['comment']] = {'proposed': row, 'candidates': {
            other['id']: {'different_fields': different_activity_fields(row, other),
                'existing': {field: other.get(field) for field in
                    ('date', 'quantity', 'unitPrice', 'fee', 'comment')},
                'source_minus_existing_seconds': str((instant(row['date']) - instant(other['date'])).total_seconds())}
            for other in candidates}, 'adoption_authorized': False}
    return result


def rounding_diagnostic(snapshot):
    """Describe fractional minor units without adopting a broker rounding rule."""
    result = {}
    for trade in snapshot['transactions']:
        product = snapshot['products'][str(trade['productId'])]
        currency = product['currency']
        quantum = adapter.CURRENCY_QUANTA.get(currency)
        if quantum is None:
            continue
        total = -number(trade['quantity']) * number(trade['price'])
        even, up = total.quantize(quantum, ROUND_HALF_EVEN), total.quantize(quantum, ROUND_HALF_UP)
        if total % quantum != 0:
            result[str(trade['id'])] = {'currency': currency, 'signed_price_times_quantity': total,
                'half_even': even, 'half_up': up, 'source_total': number(trade['total']),
                'broker_rounding_policy_proved': False}
    return result


def characterize_executions(snapshot, rows, mapping, target):
    """Per-row diagnostics do not turn a blocked full ledger into import proposals."""
    symbols = {isin: entry['symbol'] for isin, entry in mapping.items()}
    quotes = {entry['symbol']: entry['currency'] for entry in mapping.values()}
    results = {}
    outcomes = Counter()
    for row in rows:
        try:
            activity, = adapter.normalize_trades({**snapshot, 'transactions': [row]}, target, symbols, quotes)
            result = {'status': 'normalizable_in_isolation', 'activity': activity}
        except RuntimeError as error:
            result = {'status': 'blocked', 'reason': str(error)}
        outcomes[result.get('reason', result['status'])] += 1
        key = body_digest(row)
        results[key] = {'broker_id': row.get('id'), **result}
    return {'outcomes': dict(outcomes), 'rows': results, 'whole_account_import_authorized': False}


def identity_diagnostics(bodies):
    by_id = {}
    duplicate_occurrences = {}
    for digest, entry in bodies.items():
        identity = entry['body'].get('id')
        if identity is not None and identity not in (0, '0'):
            by_id.setdefault(str(identity), []).append(digest)
        paths = Counter(occurrence['path'] for occurrence in entry['occurrences'])
        repeated = {path: count for path, count in paths.items() if count > 1}
        if repeated:
            duplicate_occurrences[digest] = repeated
    return {'conflicting_nonzero_ids': {key: values for key, values in by_id.items() if len(values) > 1},
        'repeated_bodies_within_response': duplicate_occurrences}


def replay(snapshot, destination, mapping, target):
    quotes = {entry['symbol']: entry['currency'] for entry in mapping.values()}
    symbols = {isin: entry['symbol'] for isin, entry in mapping.items()}
    existing, _ = adapter.existing_activity_context(destination['activities'], target)
    proposed = adapter.normalize_trades(snapshot, target['id'], symbols, quotes)
    proposed += adapter.normalize_dividends(snapshot, target['id'], symbols, quotes)
    proposed += adapter.normalize_fees(snapshot, target['id'])
    proposed += adapter.normalize_cash_yield(snapshot, target['id'])

    def forbidden(*args, **kwargs):
        raise AssertionError('Financial dispatch forbidden in saved-input reconciliation')

    config = {'dry_run': True, 'source_account': snapshot['source_account'], 'target_account': target['id']}
    try:
        outcome = adapter.synchronize_account(config, snapshot, target, destination['activities'],
            symbols, quotes, forbidden, forbidden, now=datetime.fromisoformat(snapshot['fetched_at']))
        status = {'status': 'capture_time_proposals_only', 'proposed': len(outcome['proposed'])}
    except RuntimeError as error:
        status = {'status': 'blocked', 'reason': str(error)}
    return {'proposed_by_type': dict(Counter(row['type'] for row in proposed)),
        'destination_by_type': dict(Counter(row['type'] for row in existing if row.get('accountId') == target['id'])),
        'activity_comparisons': destination_candidates(proposed, existing, target['id']),
        'saved_input_replay': status, 'clock': 'source capture time; not fresh current-cash evidence',
        'history_completeness_verified': snapshot.get('history_completeness_verified') is True,
        'financial_callbacks': 0, 'adoptions': 0}


def archive_rows(root, read):
    """Raw unique bodies retain occurrence provenance; this is not a merged ledger."""
    bodies = {}
    executions = {}
    unverified = {}
    for path in sorted(root.glob('window-*.json')):
        if not re.fullmatch(r'window-[0-9]{3}\.json', path.name):
            continue
        envelope = decode_json(read(path))
        endpoint = envelope['capture']['endpoint']
        if envelope['capture']['http_status'] != 200:
            raise RuntimeError('Unsuccessful archived response')
        if endpoint == 'transactions':
            rows = adapter.raw_rows(envelope['body'])
            collection = executions
        elif endpoint == 'accountoverview':
            if envelope['body'].get('data') == {}:
                unverified[str(path)] = 'missing_cash_collection; not proved empty'
                continue
            rows = adapter.raw_rows(envelope['body'], 'cashMovements')
            collection = bodies
        else:
            continue
        for index, row in enumerate(rows):
            body = {key: value for key, value in row.items() if endpoint != 'accountoverview' or key != 'balance'}
            digest = body_digest(body)
            if digest not in collection:
                collection[digest] = {'body': body, 'occurrences': []}
            collection[digest]['occurrences'].append({'path': str(path), 'index': index,
                'requested_dates': envelope['capture']['dates']})
    if not bodies:
        raise RuntimeError('No raw account-overview bodies')
    return {'cash_bodies': bodies, 'execution_bodies': executions, 'unverified_cash_windows': unverified,
        'cash_identity_diagnostics': identity_diagnostics(bodies),
        'execution_identity_diagnostics': identity_diagnostics(executions)}


def plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def publish(report, output, hashes):
    """Exclusive private output; no source, pointer, symlink or existing report overwrite."""
    if output.is_symlink() or output.resolve() in {path.resolve() for path in hashes}:
        raise RuntimeError('Output aliases an input')
    output = adapter.snapshot_destination(output)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in hashes.items()):
        raise RuntimeError('Input changed during reconciliation')
    payload = yaml.safe_dump(plain(report), sort_keys=False).encode()
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('source', 'destination', 'mapping', 'target-id-file', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--archive', type=Path, action='append', default=[])
    args = parser.parse_args(argv)

    def deny_network(*unused, **kwargs):
        raise RuntimeError('Network forbidden in saved-input reconciliation')

    socket.create_connection = deny_network
    socket.socket = deny_network
    hashes = {}

    def read(path):
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if path in hashes and hashes[path] != digest:
            raise RuntimeError('Input changed during reconciliation')
        hashes[path] = digest
        return content.decode()

    source = decode_json(read(args.source))
    destination = decode_json(read(args.destination))
    mapping = yaml.safe_load(read(args.mapping))
    target_id = read(args.target_id_file).strip()
    targets = [row for row in destination['accounts']['accounts'] if row['id'] == target_id]
    if len(targets) != 1:
        raise RuntimeError('Expected one exact destination account')
    report = {'format': 1, 'diagnostic_only': True, 'network_requests': 0,
        'source_statement': compare_statement(source['cash_movements'], source['products'], source['account_report_csv']),
        'rounding': rounding_diagnostic(source), 'destination': replay(source, destination, mapping, targets[0]),
        'archives': {}}
    report['implementation'] = {name: hashlib.sha256(read(path).encode()).hexdigest()
        for name, path in {'tool': Path(__file__), 'adapter': Path(adapter.__file__),
            'core': Path(adapter.core.__file__), 'cash_rules': Path(adapter.__file__).parent / 'cash-rules.yaml'}.items()}
    for index, root in enumerate(args.archive):
        archive = archive_rows(root, read)
        bodies = archive['cash_bodies']
        statement = read(root / 'account-statement.csv')
        snapshot = decode_json(read(root / ('history-annual.json' if (root / 'history-annual.json').exists() else 'history-split.json')))
        rows = [entry['body'] for entry in bodies.values()]
        report['archives'][str(index)] = {'root': str(root),
            'raw_unique_body_counts': dict(Counter(row['type'] for row in rows)),
            'statement_comparison': compare_statement(rows, snapshot['products'], statement),
            **archive,
            'execution_diagnostics': characterize_executions(snapshot,
                [entry['body'] for entry in archive['execution_bodies'].values()], mapping, target_id),
            'rounding': rounding_diagnostic({**snapshot,
                'transactions': [entry['body'] for entry in archive['execution_bodies'].values()]}),
            'ledger_or_complete_history_proved': False}
    if len(report['archives']) == 2:
        first, second = report['archives'].values()
        cash_a, cash_b = first['cash_bodies'], second['cash_bodies']
        stable_a = {key for key, entry in cash_a.items() if entry['body'].get('id') not in (None, 0, '0')}
        stable_b = {key for key, entry in cash_b.items() if entry['body'].get('id') not in (None, 0, '0')}
        report['window_width_comparison'] = {
            'identical_nonzero_id_cash_bodies': len(stable_a & stable_b),
            'nonzero_id_bodies_only_first': len(stable_a - stable_b),
            'nonzero_id_bodies_only_second': len(stable_b - stable_a),
            'identical_execution_bodies': len(first['execution_bodies'].keys() & second['execution_bodies'].keys()),
            'executions_only_first': len(first['execution_bodies'].keys() - second['execution_bodies'].keys()),
            'executions_only_second': len(second['execution_bodies'].keys() - first['execution_bodies'].keys()),
            'cash_bodies_only_first_by_type': dict(Counter(cash_a[key]['body']['type'] for key in cash_a.keys() - cash_b.keys())),
            'cash_bodies_only_second_by_type': dict(Counter(cash_b[key]['body']['type'] for key in cash_b.keys() - cash_a.keys())),
            'history_completeness_proved': False}
    report['inputs'] = {str(path): digest for path, digest in hashes.items()}
    report['input_hashes_unchanged'] = True
    publish(report, args.output, hashes)
    summary = report['source_statement']
    print(json.dumps({'source_rows': summary['source_rows'], 'statement_rows': summary['statement_rows'],
        'exact_minute_multiset_matches': summary['exact_minute_multiset_matches'],
        'source_only_rows': summary['source_only_rows'], 'statement_only_rows': summary['statement_only_rows'],
        'proposed_by_type': report['destination']['proposed_by_type'],
        'saved_input_replay_status': report['destination']['saved_input_replay']['status'],
        'network_requests': 0, 'financial_callbacks': 0, 'adoptions': 0, 'input_hashes_unchanged': True}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, yaml.YAMLError):
        print('Saved-input reconciliation failed; preserve inputs and inspect locally', file=sys.stderr)
        raise SystemExit(1) from None
