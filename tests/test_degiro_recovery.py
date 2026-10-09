"""Durable intent and restart regressions; synthetic inputs and private tmp state."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
import requests

import degiro_to_ghostfolio as adapter
from test_degiro_sync import NOW, TARGET, MAPPING, QUOTES, activity_row, opening_holding, response, snapshot


@pytest.fixture
def config(tmp_path):
    tmp_path.chmod(0o700)
    return {'source_account': '123', 'target_account': 'target-a', 'dry_run': False,
            'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path)}


def synchronize(config, snapshot, importer, writer=lambda *args: True):
    return adapter.synchronize_account(config, snapshot, TARGET,
        {'activities': [opening_holding()], 'count': 1}, MAPPING, QUOTES,
        importer, writer, now=NOW)


def document(config):
    return yaml.safe_load(next(Path(config['state_dir']).glob('*.yaml')).read_text())


def pending_import(config, snapshot):
    def lost(batch):
        raise TimeoutError('PRIVATE-SENTINEL')
    with pytest.raises(RuntimeError, match='cash blocked'):
        synchronize(config, snapshot, lost)
    return document(config)['pending']


def test_intent_is_private_and_durable_before_dispatch(config, snapshot):
    calls = []
    def importer(batch):
        stored = document(config)
        assert stored['pending']['kind'] == 'import'
        assert list(stored['pending']['payload'].values()) == sorted(batch, key=lambda a: a['comment'])
        assert stored['owner'] == {'source': '123', 'target': 'target-a', 'host': 'http://localhost:3333'}
        assert 'token' not in str(stored)
        calls.append(True)
        return deepcopy(batch), True
    assert len(synchronize(config, snapshot, importer)['accepted']) == 3
    assert len(calls) == 2
    assert document(config)['pending'] is None
    assert len(document(config)['resolved']) == 3
    for path in Path(config['state_dir']).iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


def test_lost_response_restart_never_dispatches_again(config, snapshot):
    pending_import(config, snapshot)
    script = '''
import json, sys
import degiro_to_ghostfolio as adapter
config = json.loads(sys.argv[1])
with adapter.account_journal(config) as journal:
    assert journal['document']['pending']['kind'] == 'import'
print('PENDING')
'''
    persisted_config = {key: value for key, value in config.items() if not key.startswith('_')}
    result = subprocess.run([sys.executable, '-c', script, json.dumps(persisted_config)],
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'PENDING'
    fresh_config = deepcopy(config)
    fresh_config.pop('_uncertain_import_accounts', None)
    with pytest.raises(RuntimeError, match='durable write intent'):
        synchronize(fresh_config, snapshot, lambda *args: pytest.fail('Restart replayed POST'))


@pytest.mark.parametrize('evidence', ['empty', 'partial', 'changed', 'foreign', 'duplicate', 'count', 'redacted'])
def test_insufficient_readback_never_clears_pending(config, snapshot, evidence):
    intent = pending_import(config, snapshot)
    rows = [activity_row(a, str(i)) for i, a in enumerate(intent['payload'].values())]
    if evidence == 'empty':
        rows = []
    elif evidence == 'partial':
        rows.pop()
    elif evidence == 'changed':
        rows[0]['fee'] += 1
    elif evidence == 'foreign':
        rows[0]['accountId'] = 'other'
    elif evidence == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif evidence == 'redacted':
        rows[0]['quantity'] = None
    body = {'activities': rows, 'count': len(rows) + (1 if evidence == 'count' else 0)}
    with pytest.raises(RuntimeError):
        adapter.resolve_import_intent(config, body, expected_intent_id=intent['id'])
    assert document(config)['pending'] == intent


def test_complete_positive_readback_explicitly_resolves_without_replay(config, snapshot):
    intent = pending_import(config, snapshot)
    rows = [activity_row(a, str(i)) for i, a in enumerate(intent['payload'].values())]
    assert adapter.resolve_import_intent(config, {'activities': rows, 'count': len(rows)},
        expected_intent_id=intent['id']) == 2
    state = document(config)
    assert state['pending'] is None and intent['id'] in state['resolved']


@pytest.mark.parametrize('identity', [None, True, 123, '', 'old-id', 'a' * 31, 'a' * 33, 'A' * 32])
def test_invalid_expected_request_identity_preserves_journal(config, snapshot, identity):
    pending_import(config, snapshot)
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='Invalid expected'):
        adapter.resolve_import_intent(config, {}, expected_intent_id=identity)
    assert path.read_bytes() == before


def test_request_selection_is_mandatory(config, snapshot):
    intent = pending_import(config, snapshot)
    with pytest.raises(TypeError):
        adapter.resolve_import_intent(config, {'activities': [], 'count': 0})
    assert document(config)['pending'] == intent


def test_old_request_proof_cannot_resolve_successor_with_same_payload(config, snapshot):
    intent = pending_import(config, snapshot)
    rows = [activity_row(a, str(i)) for i, a in enumerate(intent['payload'].values())]
    body = {'activities': rows, 'count': len(rows)}
    assert adapter.resolve_import_intent(config, body, expected_intent_id=intent['id']) == 2
    # Simulate a later separately authorized request, preserving identical DTOs.
    with adapter.account_journal(config) as journal:
        successor = adapter.begin_intent(journal, 'import', deepcopy(intent['payload']))
        path = journal['path']
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='identity changed'):
        adapter.resolve_import_intent(config, body, expected_intent_id=intent['id'])
    assert path.read_bytes() == before
    assert document(config)['pending']['id'] == successor
    with pytest.raises(RuntimeError, match='durable write intent'):
        synchronize(config, snapshot, lambda *args: pytest.fail('Successor replayed'))


@pytest.mark.parametrize('confirm', [False, True])
def test_authenticated_recovery_holds_lock_and_uses_only_get(config, snapshot, monkeypatch, confirm):
    intent = pending_import(config, snapshot)
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    rows = [opening_holding()] + [activity_row(a, str(i)) for i, a in enumerate(intent['payload'].values())]
    calls = []
    def send(session, request, **options):
        calls.append(request)
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer TOKEN-SENTINEL'
        assert session.trust_env is False and options['allow_redirects'] is False
        assert options['timeout'] == (10, 60)
        with pytest.raises(RuntimeError, match='Another synchronization'):
            with adapter.account_journal(config):
                pytest.fail('Recovery failed to hold account lock across readback')
        return response(TARGET if request.url.endswith('/target-a') else {'activities': rows, 'count': len(rows)})
    monkeypatch.setattr(requests.Session, 'send', send)
    result = adapter.readback_import_intent({**config, 'ghost_token': 'TOKEN-SENTINEL'},
        expected_intent_id=intent['id'], confirm=confirm)
    assert result['matched'] == 2 and result['confirmed'] is confirm
    assert len(result['snapshot_sha256']) == 64
    assert [r.url for r in calls] == ['http://localhost:3333/api/v1/account/target-a',
                                     'http://localhost:3333/api/v1/activities']
    if confirm:
        assert document(config)['pending'] is None
    else:
        assert path.read_bytes() == before


@pytest.mark.parametrize('failure', ['stale-id', 'cash', 'invalid-confirm', 'unsafe-origin'])
def test_recovery_preconditions_fail_before_http(config, snapshot, monkeypatch, failure):
    intent = pending_import(config, snapshot)
    config['ghost_token'] = 'TOKEN-SENTINEL'
    identity, confirm = intent['id'], True
    if failure == 'stale-id':
        identity = 'a' * 32 if intent['id'] != 'a' * 32 else 'b' * 32
    elif failure == 'cash':
        with adapter.account_journal(config) as journal:
            journal['document']['pending']['kind'] = 'cash'
            adapter.write_journal(journal)
    elif failure == 'unsafe-origin':
        config['ghost_host'] = 'https://evil.example'
    else:
        confirm = 'true'
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **k: pytest.fail('Invalid recovery sent HTTP'))
    with pytest.raises(RuntimeError):
        adapter.readback_import_intent(config, expected_intent_id=identity, confirm=confirm)
    assert path.read_bytes() == before


@pytest.mark.parametrize('failure', ['account-status', 'wrong-target', 'redacted', 'inactive',
    'currency', 'activity-status', 'partial', 'malformed', 'redirect', 'transport'])
def test_failed_authenticated_readback_never_confirms(config, snapshot, monkeypatch, failure):
    intent = pending_import(config, snapshot)
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    rows = [opening_holding()] + [activity_row(a, str(i)) for i, a in enumerate(intent['payload'].values())]
    def send(session, request, **options):
        assert request.method == 'GET'
        if failure == 'transport':
            raise requests.Timeout('TOKEN-SENTINEL PRIVATE-SENTINEL')
        if failure == 'redirect':
            return response({}, 302)
        if request.url.endswith('/target-a'):
            body = deepcopy(TARGET)
            if failure == 'wrong-target':
                body['id'] = 'other'
            elif failure == 'redacted':
                body['balance'] = None
            elif failure == 'inactive':
                body['isExcluded'] = True
            elif failure == 'currency':
                body['currency'] = 'UNKNOWN'
            return response(body, 500 if failure == 'account-status' else 200)
        if failure == 'malformed':
            result = response()
            result._content = b'not-json'
            return result
        actual = rows[:-1] if failure == 'partial' else rows
        return response({'activities': actual, 'count': len(actual)},
            500 if failure == 'activity-status' else 200)
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises((RuntimeError, ValueError, requests.RequestException)) as error:
        adapter.readback_import_intent({**config, 'ghost_token': 'TOKEN-SENTINEL'},
            expected_intent_id=intent['id'], confirm=True)
    assert 'TOKEN-SENTINEL' not in str(error.value) and 'PRIVATE-SENTINEL' not in str(error.value)
    assert path.read_bytes() == before


def test_cash_response_loss_also_survives_restart(config, snapshot):
    def writer(*args):
        assert document(config)['pending']['kind'] == 'cash'
        raise TimeoutError('PRIVATE-SENTINEL')
    with pytest.raises(RuntimeError, match='durably fenced') as error:
        synchronize(config, snapshot, lambda batch: (deepcopy(batch), True), writer)
    assert 'SENTINEL' not in str(error.value)
    assert document(config)['pending']['kind'] == 'cash'
    with pytest.raises(RuntimeError, match='durable write intent'):
        synchronize(deepcopy(config), snapshot, lambda *args: pytest.fail('Cash uncertainty replay'))
    with pytest.raises(RuntimeError, match='No recoverable'):
        adapter.resolve_import_intent(config, {'activities': [], 'count': 0},
            expected_intent_id=document(config)['pending']['id'])


def test_journal_write_failure_prevents_dispatch(config, snapshot, monkeypatch):
    def fail(*args):
        raise OSError('Synthetic disk failure')
    monkeypatch.setattr(adapter.os, 'fsync', fail)
    with pytest.raises(RuntimeError, match='cash blocked'):
        synchronize(config, snapshot, lambda *args: pytest.fail('Unflushed intent dispatched'))
    assert not list(Path(config['state_dir']).glob('.intent-*'))


def test_oversized_intent_never_replaces_readable_journal(config):
    with adapter.account_journal(config) as journal:
        adapter.write_journal(journal)
        previous = journal['path'].read_bytes()
        with pytest.raises(RuntimeError, match='budget'):
            adapter.begin_intent(journal, 'import', {'fake': 'x' * 1_000_001})
        assert journal['path'].read_bytes() == previous


def test_resolved_retention_preserves_newest_confirmations_and_pending_fence(config):
    with adapter.account_journal(config) as journal:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # Reverse insertion order proves retention follows dates, not YAML order.
        journal['document']['resolved'] = {f'{i:032x}': {
            'kind': 'cash', 'at': (start + timedelta(seconds=i)).isoformat()}
            for i in reversed(range(1005))}
        adapter.write_journal(journal)
        identity = adapter.begin_intent(journal, 'cash', {'account': 'target-a', 'balance': 12.3})
        before = document(config)
        assert len(before['resolved']) == 1005 and before['pending']['id'] == identity
        with pytest.raises(RuntimeError, match='identity changed'):
            adapter.confirm_intent(journal, 'wrong-id')
        assert document(config) == before
        adapter.confirm_intent(journal, identity)
    stored = document(config)
    assert stored['pending'] is None and len(stored['resolved']) == 1000
    assert set(stored['resolved']) == {f'{i:032x}' for i in range(6, 1005)} | {identity}
    with adapter.account_journal(config) as journal:
        pending = adapter.begin_intent(journal, 'cash', {'account': 'target-a', 'balance': 99})
    assert document(config)['pending']['id'] == pending
    with pytest.raises(RuntimeError, match='durable write intent'):
        synchronize(config, {}, lambda *args: pytest.fail('Pending cash replayed'))


@pytest.mark.parametrize('other_source', [False, True])
def test_lock_refuses_another_process(config, other_source):
    script = '''
import json, sys
import degiro_to_ghostfolio as adapter
try:
    with adapter.account_journal(json.loads(sys.argv[1])):
        raise AssertionError('Concurrent account lock admitted')
except RuntimeError as error:
    assert str(error) == 'Another synchronization owns this account'
print('LOCKED')
'''
    with adapter.account_journal(config):
        second = {**config, 'source_account': '456'} if other_source else config
        result = subprocess.run([sys.executable, '-c', script, json.dumps(second)],
            text=True, capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout.strip() == 'LOCKED'


def test_another_source_cannot_replace_recorded_target_ownership(config):
    with adapter.account_journal(config) as journal:
        adapter.write_journal(journal)
    with pytest.raises(RuntimeError, match='Invalid private'):
        with adapter.account_journal({**config, 'source_account': '456'}):
            pytest.fail('Different source bypassed account owner')


@pytest.mark.parametrize('mutation', ['public-directory', 'symlink-directory', 'public-lock',
    'symlink-lock', 'symlink-journal', 'public-journal', 'corrupt', 'wrong-owner', 'oversized'])
def test_unsafe_or_corrupt_state_blocks_before_callback(config, snapshot, mutation, tmp_path):
    with adapter.account_journal(config) as journal:
        adapter.write_journal(journal)
        journal_path = journal['path']
    directory = Path(config['state_dir'])
    lock = next(directory.glob('*.lock'))
    if mutation == 'public-directory':
        directory.chmod(0o755)
    elif mutation == 'symlink-directory':
        alias = tmp_path / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        config['state_dir'] = str(alias)
    elif mutation == 'public-lock':
        lock.chmod(0o644)
    elif mutation == 'symlink-lock':
        other = directory / 'other'
        lock.rename(other)
        lock.symlink_to(other)
    elif mutation == 'symlink-journal':
        other = directory / 'other'
        journal_path.rename(other)
        journal_path.symlink_to(other)
    elif mutation == 'public-journal':
        journal_path.chmod(0o644)
    elif mutation == 'corrupt':
        journal_path.write_text('invalid: [')
    elif mutation == 'wrong-owner':
        state = yaml.safe_load(journal_path.read_text())
        state['owner']['source'] = '456'
        journal_path.write_text(yaml.safe_dump(state))
    else:
        journal_path.write_text('x' * 1_000_001)
    with pytest.raises((RuntimeError, OSError, yaml.YAMLError)):
        synchronize(config, snapshot, lambda *args: pytest.fail('Unsafe state dispatched'))


def test_live_requires_state_but_dry_run_does_not(config, snapshot):
    config.pop('state_dir')
    with pytest.raises(RuntimeError, match='STATE_DIR'):
        synchronize(config, snapshot, lambda *args: pytest.fail('No journal dispatched'))
    config['dry_run'] = True
    assert len(synchronize(config, snapshot, lambda *args: pytest.fail('DRY_RUN POST'))['proposed']) == 3


def test_run_sync_pending_blocks_before_broker_login(config, snapshot, monkeypatch):
    pending_import(config, snapshot)
    monkeypatch.setattr(adapter, 'load_sync_config', lambda: (config, MAPPING, QUOTES))
    monkeypatch.setattr(adapter, 'read_degiro', lambda *args: pytest.fail('Pending intent logged into broker'))
    with pytest.raises(RuntimeError, match='durable write intent'):
        adapter.run_sync(NOW.date(), NOW.date())


@pytest.mark.parametrize('confirm', [False, True])
def test_recovery_cli_emits_actual_complete_readback_digest_without_private_rows(
        config, snapshot, monkeypatch, capsys, confirm):
    import hashlib
    from scripts import recover_degiro
    intent = pending_import(config, snapshot)
    rows = [opening_holding()] + [activity_row(activity, str(index))
        for index, activity in enumerate(intent['payload'].values())]
    body = {'activities': rows, 'count': len(rows)}
    expected = hashlib.sha256(json.dumps(body, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    environment = {'GHOST_HOST': config['ghost_host'], 'GHOST_TOKEN': 'TOKEN-SENTINEL',
        'GHOST_ACCOUNT_ID': config['target_account'], 'DEGIRO_ACCOUNT_ID': config['source_account'],
        'STATE_DIR': config['state_dir']}
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    calls = []
    def send(session, request, **options):
        assert request.method == 'GET'
        calls.append(request.url)
        return response(TARGET if request.url.endswith('/target-a') else body)
    monkeypatch.setattr(requests.Session, 'send', send)
    args = ['--expected-intent-id', intent['id']]
    if confirm:
        args.append('--confirm-local-state')
    assert recover_degiro.main(args) == 0
    output = capsys.readouterr()
    assert 'snapshot SHA-256=' + expected in output.out and not output.err
    assert '2 exact activities' in output.out
    for private in ('TOKEN-SENTINEL', intent['id'], 'target-a', 'DEGIRO#'):
        assert private not in output.out
    assert len(calls) == 2
    if confirm:
        assert document(config)['pending'] is None
    else:
        assert path.read_bytes() == before
