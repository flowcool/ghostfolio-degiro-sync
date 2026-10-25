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


def prepare_apply(tmp_path, snapshot, destination_version='3.86.0'):
    inputs, rows = saved_inputs(tmp_path, snapshot)
    config = yaml.safe_load(inputs.read_text())
    for index, row in enumerate(rows):
        if row['assetProfile']['dataSource'] == 'MANUAL':
            row['assetProfile']['symbol'] = f'00000000-0000-4000-8000-{index:012d}'
    destination = tmp_path / 'destination.json'
    destination.write_text(json.dumps({'count': len(rows), 'activities': rows}, default=float))
    config['snapshot']['sha256'] = migration.digest(destination.read_bytes())
    config['snapshot']['destination_version'] = destination_version
    inputs.write_text(yaml.safe_dump(config))
    manifest_hash = migration.preview(inputs, tmp_path / 'review')
    manifest = tmp_path / 'review/manifest.yaml'
    reviewed = migration.keyed_yaml(manifest.read_bytes())
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    approval = {'schema': 'degiro-migration-approval-v1', 'authorization': 'apply-reviewed-comments',
        'host': 'https://portfolio.example', 'owner_id': 'synthetic-owner',
        'manifest_sha256': manifest_hash, 'destination_version': destination_version,
        'destination_image': 'sha256:' + 'a' * 64,
        'target_source_commit': 'ef47c0d1b2c48fa4e97fb381561b514e657928cf',
        'state_dir': str(state), 'writers_stopped': True, 'requests_settled': True,
        'operation_plan_ref': 'synthetic-plan', 'backup_ref': 'synthetic-recoverable-backup',
        'writer_exclusion_ref': 'synthetic-exclusive-writers', 'settlement_ref': 'synthetic-settled',
        'write_count': len(reviewed['replacements']), 'batch_size': 1, 'pause_seconds': '0',
        'qualifications': {migration.update_class(row): {
            key: {'status': 'pass', 'source_refs': ['synthetic-lab-exact-image']}
            for key in ('source_identity', 'target_dto', 'manual_zero_uuid', 'background_effects', 'pacing', 'reversal')}
            for row in rows if row['id'] in reviewed['replacements']}}
    permit = tmp_path / 'approval.yaml'
    permit.write_bytes(migration.yaml_bytes(approval))
    return inputs, manifest, manifest_hash, permit, migration.digest(permit.read_bytes()), tmp_path / 'operation.yaml', rows


def apply_fake(tmp_path, snapshot, monkeypatch, effect=None, destination_version='3.86.0'):
    args = prepare_apply(tmp_path, snapshot, destination_version)
    rows = migration.exact_json((tmp_path / 'destination.json').read_bytes())['activities']
    puts = []
    def request(method, host, token, row_id=None, payload=None):
        assert host == 'https://portfolio.example' and token == 'synthetic-token'
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        journal = migration.keyed_yaml(args[5].read_bytes())
        assert journal['rows'][row_id]['status'] == 'pending'
        assert journal['rows'][row_id]['request_body_sha256'] == migration.digest(migration.numeric_json(payload))
        puts.append(row_id)
        if effect:
            effect(rows, row_id, payload)
        else:
            next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
    monkeypatch.setattr(migration, 'maintenance_request', request)
    return args, rows, puts


def test_apply_only_changes_reviewed_comments_with_intent_first(tmp_path, snapshot, monkeypatch):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch)
    before = deepcopy(rows)
    migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert len(puts) == 3
    assert [{**row, 'comment': old['comment']} for row, old in zip(rows, before)] == before
    assert migration.keyed_yaml(args[5].read_bytes())['status'] == 'complete'
    with pytest.raises(RuntimeError, match='Existing'):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')


@pytest.mark.parametrize('version', ['3.86.0', '3.86.0+build.7', '3.93.0', '3.100.0',
                                    '3.93.0-rc.1', '4.0.0'])
def test_apply_and_rollback_accept_newer_versions_without_source_pin(tmp_path, snapshot, monkeypatch, version):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, destination_version=version)
    permit = migration.keyed_yaml(args[3].read_bytes())
    permit.pop('target_source_commit')
    args[3].write_bytes(migration.yaml_bytes(permit))
    args = (*args[:4], migration.digest(args[3].read_bytes()), *args[5:])
    before = deepcopy(rows)
    migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert len(puts) == 3
    assert [{**row, 'comment': old['comment']} for row, old in zip(rows, before)] == before
    rollback = rollback_permit(args)
    def request(method, host, token, row_id=None, payload=None):
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        puts.append(row_id)
        next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
    monkeypatch.setattr(migration, 'maintenance_request', request)
    migration.rollback(args[5], args[1], args[2], rollback, migration.digest(rollback.read_bytes()),
        'https://portfolio.example', 'synthetic-token')
    assert len(puts) == 6 and rows == before
    assert migration.keyed_yaml(args[5].read_bytes())['status'] == 'rolled_back'


@pytest.mark.parametrize('version', ['3.85.99', '2.100.0', '3.86.0-rc.1', '3.93',
                                    'latest', '03.93.0', '3.93.0-01', '3.93.0+', '3.93.0\n'])
def test_apply_refuses_unsupported_versions_before_authentication(tmp_path, snapshot, monkeypatch, version):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, destination_version=version)
    monkeypatch.setattr(migration, 'maintenance_token', lambda *a: pytest.fail('Unexpected authentication'))
    with pytest.raises(RuntimeError, match='at least 3.86.0'):
        migration.apply(*args[:6], 'https://portfolio.example', None)
    assert not puts and not args[5].exists()


@pytest.mark.parametrize('field', ['destination_version', 'destination_image'])
def test_apply_newer_version_still_requires_matching_destination(tmp_path, snapshot, monkeypatch, field):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, destination_version='3.93.0')
    permit = migration.keyed_yaml(args[3].read_bytes())
    permit[field] = '3.94.0' if field == 'destination_version' else 'sha256:' + 'b' * 64
    args[3].write_bytes(migration.yaml_bytes(permit))
    args = (*args[:4], migration.digest(args[3].read_bytes()), *args[5:])
    monkeypatch.setattr(migration, 'maintenance_token', lambda *a: pytest.fail('Unexpected authentication'))
    with pytest.raises(RuntimeError, match='Destination image or version changed'):
        migration.apply(*args[:6], 'https://portfolio.example', None)
    assert not puts and not args[5].exists()


@pytest.mark.parametrize('failure', ['timeout', 'normalization', 'protected', 'partial'])
def test_apply_stops_pending_without_retry(tmp_path, snapshot, monkeypatch, failure):
    def effect(rows, row_id, payload):
        if failure == 'timeout':
            raise RuntimeError('Uncertain request')
        next(row for row in rows if row['id'] == row_id)['comment'] = (
            'changed-by-target' if failure == 'normalization' else payload['comment'])
        if failure == 'protected':
            rows[0]['fee'] = 999
        if failure == 'partial' and row_id == 'old-1':
            raise RuntimeError('Lost response after commit')
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, effect)
    with pytest.raises(RuntimeError):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    record = migration.keyed_yaml(args[5].read_bytes())
    assert any(row['status'] == 'pending' for row in record['rows'].values())
    assert len(puts) == (2 if failure == 'partial' else 1)
    with pytest.raises(RuntimeError):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert len(puts) == (2 if failure == 'partial' else 1)


@pytest.mark.parametrize('version', ['3.86.0', '3.93.0'])
def test_apply_pending_qualification_stale_snapshot_and_decimal_loss_refuse(tmp_path, snapshot, monkeypatch, version):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, destination_version=version)
    permit = migration.keyed_yaml(args[3].read_bytes())
    for qualification in permit['qualifications'].values():
        qualification['target_dto']['status'] = 'pending'
    args[3].write_bytes(migration.yaml_bytes(permit))
    args = (*args[:4], migration.digest(args[3].read_bytes()), *args[5:])
    with pytest.raises(RuntimeError, match='qualification'):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert not puts
    row = rows[1]
    from decimal import Decimal
    row['unitPrice'] = Decimal('10.00000000000000001')
    with pytest.raises(RuntimeError, match='preserved'):
        migration.comment_payload(row, 'DEGIRO#v1#123:TRADE:10')


def test_apply_manual_uuid_zero_and_stale_protected_state(tmp_path, snapshot, monkeypatch):
    from test_degiro_cash_yield import yield_row
    snapshot['cash_movements'] += [yield_row(), yield_row('interest', 602)]
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch)
    # The first fresh snapshot includes all protected rows and rejects drift.
    rows[0]['fee'] = 1
    with pytest.raises(RuntimeError, match='context'):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert puts == []
    second = tmp_path / 'second'
    second.mkdir(mode=0o700)
    args, rows, puts = apply_fake(second, snapshot, monkeypatch)
    migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert len(puts) == 5
    zero = next(row for row in rows if str(row['comment']).endswith(':INTEREST:602'))
    assert zero['unitPrice'] == zero['fee'] == 0
    assert zero['assetProfile']['symbol'].startswith('00000000-0000-4000-8000-')


def test_apply_numeric_tokens_are_exact_and_normal_sync_stays_separate():
    from decimal import Decimal
    assert migration.numeric_json({'value': Decimal('0.165'), 'zero': Decimal('0.00')}) == b'{"value":0.165,"zero":0.00}'
    with pytest.raises(RuntimeError, match='numeric'):
        migration.numeric_json({'value': 0.165})
    with pytest.raises(RuntimeError, match='boundary'):
        migration.maintenance_request('DELETE', 'https://portfolio.example', 'synthetic-token', 'row')


def test_apply_refuses_concurrent_destination_lock(tmp_path, snapshot, monkeypatch):
    from ghostfolio_degiro_sync.journal import account_journal
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch)
    permit = migration.keyed_yaml(args[3].read_bytes())
    with account_journal({'state_dir': permit['state_dir'], 'ghost_host': permit['host'],
                          'source_account': '123', 'target_account': TARGET['id']}):
        with pytest.raises(RuntimeError, match='Another synchronization'):
            migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    assert puts == []


def test_inspect_and_rollback_preserve_new_v1_imports(tmp_path, snapshot, monkeypatch):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch)
    migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    extra = {**deepcopy(rows[1]), 'id': 'new-import', 'comment': 'DEGIRO#v1#123:TRADE:999'}
    rows.append(extra)
    capture = tmp_path / 'after.json'
    capture.write_bytes(migration.numeric_json({'count': len(rows), 'activities': rows}))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    states = migration.inspect(args[5], args[1], args[2], capture, migration.digest(capture.read_bytes()))
    assert set(states.values()) == {'converted'}
    assert all(p.read_bytes() == data for p, data in before.items())
    permit = rollback_permit(args)
    def request(method, host, token, row_id=None, payload=None):
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        record = migration.keyed_yaml(args[5].read_bytes())
        assert record['rows'][row_id]['rollback_status'] == 'pending'
        next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
    monkeypatch.setattr(migration, 'maintenance_request', request)
    migration.rollback(args[5], args[1], args[2], permit, migration.digest(permit.read_bytes()),
        'https://portfolio.example', 'synthetic-token')
    assert rows[-1] == extra
    assert all(row['comment'].startswith('DEGIRO#123:') for row in rows[1:-1])
    assert migration.keyed_yaml(args[5].read_bytes())['status'] == 'rolled_back'


def rollback_permit(args):
    permit = migration.keyed_yaml(args[3].read_bytes())
    permit['authorization'] = 'rollback-reviewed-comments'
    permit['journal_sha256'] = migration.digest(args[5].read_bytes())
    permit['settlements'] = {}
    path = args[3].with_name('rollback.yaml')
    path.write_bytes(migration.yaml_bytes(permit))
    return path


@pytest.mark.parametrize('outcome', ['old-readback', 'late-completion', 'manual-drift'])
def test_rollback_uncertain_requests_need_independent_settlement(tmp_path, snapshot, monkeypatch, outcome):
    def timeout(rows, row_id, payload):
        if outcome != 'old-readback':
            next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
        raise RuntimeError('Lost response')
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, timeout)
    with pytest.raises(RuntimeError):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    pending_id = puts[0]
    if outcome == 'manual-drift':
        next(row for row in rows if row['id'] == pending_id)['fee'] = 99
    permit = rollback_permit(args)
    def request(method, host, token, row_id=None, payload=None):
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        pytest.fail('Unsettled reversal dispatched')
    monkeypatch.setattr(migration, 'maintenance_request', request)
    with pytest.raises(RuntimeError, match='settlement'):
        migration.rollback(args[5], args[1], args[2], permit, migration.digest(permit.read_bytes()),
            'https://portfolio.example', 'synthetic-token')
    assert len(puts) == 1


@pytest.mark.parametrize('completed', [False, True])
def test_rollback_independent_settlement_controls_reversal(tmp_path, snapshot, monkeypatch, completed):
    def timeout(rows, row_id, payload):
        if completed:
            next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
        raise RuntimeError('Lost response')
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch, timeout)
    with pytest.raises(RuntimeError):
        migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    row_id = puts[0]
    permit = rollback_permit(args)
    approval = migration.keyed_yaml(permit.read_bytes())
    approval['write_count'] = int(completed)
    approval['settlements'][row_id] = {'direction': 'apply', 'outcome': 'completed' if completed else 'cancelled',
        'independent': True, 'evidence_ref': 'synthetic-independent-request-disposition'}
    permit.write_bytes(migration.yaml_bytes(approval))
    reversed_ids = []
    def request(method, host, token, target=None, payload=None):
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        reversed_ids.append(target)
        assert migration.keyed_yaml(args[5].read_bytes())['rows'][target]['rollback_status'] == 'pending'
        next(row for row in rows if row['id'] == target)['comment'] = payload['comment']
    monkeypatch.setattr(migration, 'maintenance_request', request)
    migration.rollback(args[5], args[1], args[2], permit, migration.digest(permit.read_bytes()),
        'https://portfolio.example', 'synthetic-token')
    assert reversed_ids == ([row_id] if completed else [])


def test_rollback_interruption_remains_uncertain_and_manual_drift_blocks(tmp_path, snapshot, monkeypatch):
    args, rows, puts = apply_fake(tmp_path, snapshot, monkeypatch)
    migration.apply(*args[:6], 'https://portfolio.example', 'synthetic-token')
    permit = rollback_permit(args)
    def request(method, host, token, row_id=None, payload=None):
        if method == 'GET':
            return {'count': len(rows), 'activities': deepcopy(rows)}
        next(row for row in rows if row['id'] == row_id)['comment'] = payload['comment']
        raise RuntimeError('Lost reversal response')
    monkeypatch.setattr(migration, 'maintenance_request', request)
    with pytest.raises(RuntimeError):
        migration.rollback(args[5], args[1], args[2], permit, migration.digest(permit.read_bytes()),
            'https://portfolio.example', 'synthetic-token')
    record, reviewed = migration.migration_journal(args[5], args[1], args[2])
    states = migration.inspect_rows(record, {'count': len(rows), 'activities': rows}, reviewed['snapshot'])
    assert 'uncertain:original' in states.values()
    permit = rollback_permit(args)
    with pytest.raises(RuntimeError, match='settlement'):
        migration.rollback(args[5], args[1], args[2], permit, migration.digest(permit.read_bytes()),
            'https://portfolio.example', 'synthetic-token')
    # A changed context is visible even after a settled successful conversion.
    changed = next(row for row in rows if row['comment'] and row['comment'].startswith('DEGIRO#v1#'))
    changed['fee'] = 999
    states = migration.inspect_rows(record, {'count': len(rows), 'activities': rows}, reviewed['snapshot'])
    assert states[changed['id']] == 'changed'
