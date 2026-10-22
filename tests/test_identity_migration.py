"""Historical maintenance uses synthetic saved inputs and isolated journals."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
import yaml

from test_degiro_sync import MAPPING, NOW, QUOTES, TARGET, activity_row, opening_holding, snapshot
from ghostfolio_degiro_sync import diagnostics
import degiro_identity_maintenance as migration


def saved_inputs(tmp_path, snapshot, rows=None):
    snapshot = deepcopy(snapshot)
    snapshot.update(from_date='2025-01-01', to_date='2026-10-08')
    snapshot['_diagnostic_wire'] = [
        {'path': '/transactions', 'body': json.dumps({'data': snapshot['transactions']})},
        {'path': '/accountoverview', 'body': json.dumps({'data': {'cashMovements': snapshot['cash_movements']}})},
        {'path': '/products/info', 'body': json.dumps({'data': snapshot['products']})}]
    expected = diagnostics.exact_source_activities(snapshot, TARGET['id'], MAPPING, QUOTES)
    if rows is None:
        rows = [opening_holding(), *[activity_row(a, f'old-{i}') for i, a in enumerate(expected)]]
        for row in rows:
            if row['comment']:
                row['comment'] = row['comment'].replace('DEGIRO#v1#', 'DEGIRO#')
    for row in rows:
        row.setdefault('tags', [])
        row.setdefault('isDraft', False)
        row.setdefault('userId', 'synthetic-owner')
    def save(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data, default=lambda value: float(value)))
        return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    source = save('source.json', snapshot)
    source['source_account'] = '123'
    destination = save('destination.json', {'count': len(rows), 'activities': rows})
    destination.update(complete=True, unredacted=True, count=len(rows), capture_ref='synthetic-capture',
        captured_at=NOW.isoformat(), destination_version='2.0.0', destination_image='sha256:' + 'a' * 64)
    mapping = tmp_path / 'mapping.yaml'
    mapping.write_text(yaml.safe_dump({'symbols': MAPPING, 'quote_currencies': QUOTES}))
    config = {'schema': 'degiro-migration-inputs-v1', 'tool_commit': 'b' * 40,
        'inventory_complete': True, 'accounts': {'123': TARGET}, 'clock': NOW.isoformat(),
        'mapping': {'path': mapping.name, 'sha256': hashlib.sha256(mapping.read_bytes()).hexdigest()},
        'reports': {'saved': source}, 'replay_order': ['saved'], 'snapshot': destination}
    inputs = tmp_path / 'inputs.yaml'
    inputs.write_text(yaml.safe_dump(config))
    return inputs, rows


def test_preview_preserves_inputs_and_compares_full_selection(tmp_path, snapshot, monkeypatch):
    inputs, rows = saved_inputs(tmp_path, snapshot)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a: pytest.fail('network forbidden'))
    monkeypatch.setenv('DRY_RUN', '0')
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    first = migration.preview(inputs, tmp_path / 'first')
    second = migration.preview(inputs, tmp_path / 'second')
    assert first == second
    manifest = migration.keyed_yaml((tmp_path / 'first/manifest.yaml').read_bytes())
    assert len(manifest['rows']) == len(rows)
    assert manifest['counts'] == {'eligible': 3, 'manual/other broker': 1}
    assert manifest['selection_proof']['equal'] is True
    assert manifest['selection_proof']['before'] == manifest['selection_proof']['after']
    assert len(manifest['replacements']) == 3
    assert all(p.read_bytes() == data for p, data in before.items())
    assert (tmp_path / 'first').stat().st_mode & 0o777 == 0o700
    assert (tmp_path / 'first/manifest.yaml').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('change,status', [('old','unproven'), ('amount','conflicting'),
    ('duplicate','ambiguous'), ('versioned','already versioned'), ('inactive','unsupported'),
    ('remap','conflicting'), ('bad-identity','unsupported')])
def test_preview_all_history_and_unsafe_ownership(tmp_path, snapshot, change, status):
    _, rows = saved_inputs(tmp_path, snapshot)
    target = rows[1]
    if change == 'old':
        target['date'] = '2010-01-01T00:00:00Z'
        target['comment'] = 'DEGIRO#123:TRADE:999'
    elif change == 'amount':
        target['fee'] = 999
    elif change == 'duplicate':
        rows.append({**target, 'id': 'duplicate'})
    elif change == 'versioned':
        target['comment'] = target['comment'].replace('DEGIRO#', 'DEGIRO#v1#')
    elif change == 'inactive':
        target['isDraft'] = True
    elif change == 'remap':
        target['accountId'] = 'other-target'
    else:
        target['comment'] = 'DEGIRO#123:TRADE:0'
    inputs, _ = saved_inputs(tmp_path, snapshot, rows)
    migration.preview(inputs, tmp_path / 'review')
    result = migration.keyed_yaml((tmp_path / 'review/manifest.yaml').read_bytes())
    assert result['rows'][target['id']]['status'] == status
    assert target['id'] not in result['replacements']
    assert len(result['rows']) == len(rows)


def test_preview_missing_exact_source_keeps_legacy_rows(tmp_path, snapshot):
    inputs, _ = saved_inputs(tmp_path, snapshot)
    source = json.loads((tmp_path / 'source.json').read_text())
    del source['_diagnostic_wire']
    (tmp_path / 'source.json').write_text(json.dumps(source))
    config = yaml.safe_load(inputs.read_text())
    config['reports']['saved']['sha256'] = hashlib.sha256((tmp_path / 'source.json').read_bytes()).hexdigest()
    inputs.write_text(yaml.safe_dump(config))
    migration.preview(inputs, tmp_path / 'review')
    manifest = migration.keyed_yaml((tmp_path / 'review/manifest.yaml').read_bytes())
    assert not manifest['replacements']
    assert manifest['counts']['unproven'] == 3


def test_preview_rejects_duplicate_yaml_and_output_overlap(tmp_path, snapshot):
    inputs, _ = saved_inputs(tmp_path, snapshot)
    with pytest.raises(RuntimeError, match='overlap'):
        migration.preview(inputs, tmp_path)
    inputs.write_text(inputs.read_text() + '\nclock: duplicate\n')
    with pytest.raises(RuntimeError, match='duplicate YAML'):
        migration.preview(inputs, tmp_path / 'review')


def test_preview_manual_zero_uuid_and_all_kinds(tmp_path, snapshot):
    from test_degiro_cash_yield import yield_row
    snapshot['cash_movements'] += [yield_row(), yield_row('interest', 602)]
    inputs, rows = saved_inputs(tmp_path, snapshot)
    for index, row in enumerate(rows):
        if row['assetProfile']['dataSource'] == 'MANUAL':
            row['assetProfile']['symbol'] = f'00000000-0000-4000-8000-{index:012d}'
    inputs, _ = saved_inputs(tmp_path, snapshot, rows)
    migration.preview(inputs, tmp_path / 'review')
    manifest = migration.keyed_yaml((tmp_path / 'review/manifest.yaml').read_bytes())
    assert manifest['counts']['eligible'] == 5
    assert len(manifest['replacements']) == 5
    assert manifest['selection_proof']['before'] == manifest['selection_proof']['after']


def test_preview_changed_complete_selection_removes_replacements(tmp_path, snapshot, monkeypatch):
    inputs, _ = saved_inputs(tmp_path, snapshot)
    original = migration.replay_selection
    def changed(reports, rows, config, mapping):
        result = original(reports, rows, config, mapping)
        if any(str(row['comment']).startswith('DEGIRO#v1#') for row in rows):
            result['saved']['different_holdings'] = 'synthetic-drift'
        return result
    monkeypatch.setattr(migration, 'replay_selection', changed)
    migration.preview(inputs, tmp_path / 'review')
    manifest = migration.keyed_yaml((tmp_path / 'review/manifest.yaml').read_bytes())
    assert not manifest['replacements'] and manifest['selection_proof']['equal'] is False
    assert manifest['counts']['unproven'] == 3
