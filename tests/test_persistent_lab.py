"""Persistent lab safety and real orchestration checks, entirely offline."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import degiro_to_ghostfolio as adapter
from scripts import persistent_lab as runner
from scripts import prepare_lab
from scripts import run_compose_lab as wrapper
from scripts.isolated_acceptance import GHOST_IMAGE, POSTGRES_IMAGE, REDIS_IMAGE
from test_degiro_sync import activity_row


@pytest.fixture
def scenario():
    fixture = yaml.safe_load(Path('tests/fixtures/degiro_contract.yaml').read_text())
    return runner.synthetic(fixture, 'lab-account')


def test_reused_synthetic_fixture_has_exact_rolling_plan(scenario):
    snapshot, seeds, mapping, quotes = scenario
    account = {'id': 'lab-account', 'currency': 'EUR', 'balance': 0}
    body = {'count': 1, 'activities': [activity_row(seeds[0], 'opening')]}
    planned = adapter.synchronize_locked({'source_account': '123', 'target_account': 'lab-account',
        'sync_mode': 'rolling', 'dry_run': True}, snapshot, account, body, mapping, quotes,
        None, None, now=adapter.prospective_instant(snapshot['fetched_at']))
    assert planned['rolling_verified'] and not planned['history_verified']
    assert Counter(row['type'] for row in planned['proposed']) == {'SELL': 1, 'FEE': 1, 'DIVIDEND': 1}
    assert planned['cash'] == 12.3 and planned['accepted'] == []


@pytest.mark.parametrize('lose_reply', [False, True])
def test_lifecycle_exact_native_readback_repeat_and_recovery(tmp_path, monkeypatch, scenario, lose_reply):
    snapshot, seeds, mapping, quotes = scenario
    account = {'id': 'lab-account', 'currency': 'EUR', 'balance': 0}
    body = {'count': 1, 'activities': [activity_row(seeds[0], 'opening')]}
    config = {'ghost_host': runner.HOST, 'source_account': '123', 'target_account': 'lab-account', 'sync_mode': 'rolling',
        'dry_run': True, 'state_dir': str(tmp_path)}
    expected = adapter.synchronize_locked(config, snapshot, account, body, mapping, quotes,
        None, None, now=adapter.prospective_instant(snapshot['fetched_at']))['proposed']
    def call(method, path):
        return deepcopy(body if path == '/api/v1/activities' else account)
    def imported(cfg, batch):
        for row in batch:
            body['activities'].append(activity_row(row, row['comment']))
        body['count'] = len(body['activities'])
        return deepcopy(batch), True
    def cash(cfg, identity, value):
        account['balance'] = value
        return True
    monkeypatch.setattr(adapter, 'ghost_transport', lambda *args: __import__('contextlib').nullcontext())
    monkeypatch.setattr(runner.core, 'ghost_import_activities', imported)
    monkeypatch.setattr(runner.core, 'ghost_update_cash_balance', cash)
    result = runner.lifecycle(config, snapshot, mapping, quotes, call, expected, lose_reply)
    assert result['created'] == 3 and result['repeat_created'] == 0
    assert result['positive_restart_verified'] is lose_reply
    assert account['balance'] == 12.3 and body['count'] == 4


def test_seed_remapping_preserves_financial_values_and_ignores_foreign_account(scenario):
    snapshot, seeds, unused, quotes = scenario
    row = activity_row(seeds[0], 'old-id')
    foreign = {**deepcopy(row), 'id': 'foreign-id', 'accountId': 'foreign'}
    destination = {'account': {'id': 'lab-account'},
        'activities': {'count': 2, 'activities': [row, foreign]}}
    original = deepcopy(destination)
    result = runner.remap_seeds(destination, 'new-lab')
    assert result == [{**seeds[0], 'accountId': 'new-lab'}]
    assert destination == original


@pytest.fixture
def private_inputs(tmp_path, scenario):
    snapshot, seeds, mapping, quotes = scenario
    destination = {'account': {'id': 'lab-account', 'currency': 'EUR', 'balance': 0},
        'activities': {'count': 1, 'activities': [activity_row(seeds[0], 'old-id')]}}
    values = {'broker': snapshot, 'destination': destination,
        'mapping': {'US0378331005': {'symbol': 'TEST', 'currency': 'USD'}}}
    args = SimpleNamespace(output_directory=str(tmp_path / 'prepared'))
    for name, value in values.items():
        path = tmp_path / (name + ('.yaml' if name == 'mapping' else '.json'))
        raw = yaml.safe_dump(value).encode() if name == 'mapping' else json.dumps(value).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        setattr(args, name, str(path))
        setattr(args, name + '_sha256', hashlib.sha256(raw).hexdigest())
    return args


def test_private_preparation_and_pinned_load_preserve_inputs(private_inputs):
    originals = {name: Path(getattr(private_inputs, name)).read_bytes()
        for name in ('broker', 'destination', 'mapping')}
    digest = prepare_lab.prepare(private_inputs)
    root = Path(private_inputs.output_directory)
    manifest, snapshot, destination, mapping, quotes = runner.load_replay(root, digest)
    assert manifest['seed_count'] == 1 and len(manifest['expected_proposals']) == 3
    assert manifest['expected_cash'] == 12.3
    assert root.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    assert originals == {name: Path(getattr(private_inputs, name)).read_bytes() for name in originals}
    with pytest.raises(FileExistsError):
        prepare_lab.prepare(private_inputs)


@pytest.mark.parametrize('change', ['hash', 'unsafe', 'symlink', 'alias'])
def test_preparation_refuses_changed_unsafe_or_aliased_inputs(private_inputs, change):
    path = Path(private_inputs.broker)
    if change == 'hash':
        path.write_text('{}')
    elif change == 'unsafe':
        path.chmod(0o644)
    elif change == 'symlink':
        original = path.with_suffix('.original')
        path.rename(original)
        path.symlink_to(original)
    else:
        private_inputs.output_directory = str(path.parent)
    with pytest.raises(RuntimeError):
        prepare_lab.prepare(private_inputs)
    if change != 'alias':
        assert not Path(private_inputs.output_directory).exists()


@pytest.mark.parametrize('changed', ['manifest', 'broker', 'profiles'])
def test_replay_binding_detects_retained_input_changes(private_inputs, changed):
    digest = prepare_lab.prepare(private_inputs)
    root = Path(private_inputs.output_directory)
    path = root / {'manifest': 'manifest.yaml', 'broker': 'broker.json', 'profiles': 'profiles.json'}[changed]
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(RuntimeError, match='Changed prospective evidence'):
        runner.load_replay(root, digest)


def inspected(monkeypatch, change=None):
    labels = {'com.docker.compose.project': wrapper.PROJECT,
        'com.docker.compose.service': 'ghostfolio', 'io.flowcool.degiro-lab': wrapper.MARKER}
    network_labels = {'com.docker.compose.project': wrapper.PROJECT, 'com.docker.compose.network': 'lab'}
    ports = {'3333/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3334'}]}
    if change == 'project':
        labels['com.docker.compose.project'] = 'ghostfolio-production'
    if change == 'marker':
        labels.pop('io.flowcool.degiro-lab')
    if change == 'public':
        ports['3333/tcp'][0]['HostIp'] = '0.0.0.0'
    def command(args, **kwargs):
        if args[-3:] == ['ps', '-q', 'ghostfolio']:
            return 'server'
        if args[:3] == ['docker', 'network', 'inspect']:
            return '\n'.join(json.dumps(value) for value in
                (change != 'external', network_labels, {'server': {}}))
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps({'io.flowcool.degiro-lab': wrapper.MARKER} if change != 'image' else {})
        if 'Config.Labels "com.docker.compose.project"' in args[-2]:
            return 'foreign' if change == 'foreign' else wrapper.PROJECT
        return '\n'.join(json.dumps(value) for value in
            (labels, {'lab': {}}, ports, change != 'stopped', 'sha256:fixture-image'))
    monkeypatch.setattr(wrapper, 'command', command)


def test_host_guard_accepts_only_owned_internal_localhost_stack(monkeypatch):
    inspected(monkeypatch)
    wrapper.verify_stack(['docker', 'compose'])


@pytest.mark.parametrize('change', ['project', 'marker', 'public', 'external', 'foreign', 'stopped', 'image'])
def test_host_guard_refuses_foreign_or_exposed_stack(monkeypatch, change):
    inspected(monkeypatch, change)
    with pytest.raises(RuntimeError):
        wrapper.verify_stack(['docker', 'compose'])


def test_compose_reuses_pins_and_separates_runtime_from_lab():
    lab = yaml.safe_load(Path('compose.lab.yaml').read_text())
    production = yaml.safe_load(Path('compose.yaml').read_text())
    assert lab['services']['postgres']['image'] == POSTGRES_IMAGE
    assert lab['services']['redis']['image'] == REDIS_IMAGE
    assert 'FROM ' + GHOST_IMAGE in Path('lab/Dockerfile').read_text()
    assert lab['networks'] == {'lab': {'internal': True}}
    checker = lab['services']['lab-check']
    assert checker['user'] == '10001:10001' and checker['read_only'] is True
    assert set(checker['environment']) == {'DEGIRO_PERSISTENT_LAB'}
    assert checker['profiles'] == ['tests'] and 'CRON' not in checker['environment']
    assert all(mount['read_only'] for mount in checker['volumes'] if mount['target'] != '/runs')
    runtime = production['services']['degiro-sync']
    assert runtime['environment']['DRY_RUN'] == '${DRY_RUN:-1}'
    assert runtime['environment']['SYNC_MODE'] == 'rolling'
    assert runtime['environment']['CRON'] == '${CRON:-}'
    assert runtime['user'] == '10001:10001' and runtime['read_only'] is True
    assert runtime['restart'] == 'no' and runtime['cap_drop'] == ['ALL']
    assert runtime['security_opt'] == ['no-new-privileges:true']
    assert production['networks']['ghostfolio']['external'] is True


@pytest.mark.parametrize('change', [None, 'credentials', 'network', 'mount', 'privileged', 'extra_host', 'timeout'])
def test_host_runner_arms_only_checked_definition(monkeypatch, change):
    inspected(monkeypatch)
    inspected_command = wrapper.command
    service = yaml.safe_load(Path('compose.lab.yaml').read_text())['services']['lab-check']
    rendered = {'services': {'lab-check': service}, 'networks': {'lab': {'name': 'lab', 'internal': True}}}
    if change == 'credentials':
        service['environment']['GHOST_TOKEN'] = 'forbidden-synthetic-bearer'
    elif change == 'network':
        rendered['networks']['lab']['name'] = 'production'
    elif change == 'mount':
        service['volumes'][0]['read_only'] = False
    elif change == 'privileged':
        service['privileged'] = True
    elif change == 'extra_host':
        service['extra_hosts'] = ['ghostfolio=192.0.2.1']
    launched = []
    def command(args, **kwargs):
        if args[-3:] == ['config', '--format', 'json']:
            return json.dumps(rendered)
        if 'run' in args:
            launched.append((args, kwargs))
            if change == 'timeout':
                raise subprocess.TimeoutExpired(args, 600)
            return 'PASS'
        return inspected_command(args, **kwargs)
    monkeypatch.setattr(wrapper, 'command', command)
    removed = []
    monkeypatch.setattr(wrapper, 'remove_owned_worker', lambda name, marker: removed.append((name, marker)))
    args = SimpleNamespace(compose_file='compose.lab.yaml', scenario='synthetic', manifest_sha256='0' * 64)
    if change:
        with pytest.raises(RuntimeError):
            wrapper.invoke(args)
        if change == 'timeout':
            assert len(launched) == len(removed) == 1
            command_args = launched[0][0]
            assert command_args[command_args.index('--name') + 1] == removed[0][0]
            assert command_args[command_args.index('--label') + 1].endswith('=' + removed[0][1])
        else:
            assert launched == removed == []
    else:
        wrapper.invoke(args)
        assert len(launched) == 1
        assert launched[0][1]['environment']['DEGIRO_PERSISTENT_LAB'] == 'persistent-v1'
        assert launched[0][1]['timeout'] == 600


def test_replay_cash_mismatch_refused_before_any_write(tmp_path, monkeypatch, scenario):
    snapshot, seeds, mapping, quotes = scenario
    account = {'id': 'lab-account', 'currency': 'EUR', 'balance': 0}
    body = {'count': 1, 'activities': [activity_row(seeds[0], 'opening')]}
    config = {'ghost_host': runner.HOST, 'source_account': '123', 'target_account': 'lab-account',
        'sync_mode': 'rolling', 'dry_run': True, 'state_dir': str(tmp_path)}
    expected = adapter.synchronize_locked(config, snapshot, account, body, mapping, quotes,
        None, None, now=adapter.prospective_instant(snapshot['fetched_at']))['proposed']
    def call(method, path):
        assert method == 'GET'
        return deepcopy(body if path == '/api/v1/activities' else account)
    monkeypatch.setattr(adapter, 'ghost_transport', lambda *args: __import__('contextlib').nullcontext())
    with pytest.raises(RuntimeError):
        runner.lifecycle(config, snapshot, mapping, quotes, call, expected, expected_cash=12.31)
    assert not list(tmp_path.glob('*.yaml'))


@pytest.mark.parametrize('owned', [True, False])
def test_timeout_cleanup_requires_exact_worker_ownership(monkeypatch, owned):
    calls = []
    labels = {'com.docker.compose.project': wrapper.PROJECT,
        'com.docker.compose.service': 'lab-check', 'io.flowcool.degiro-lab-worker': 'marker'}
    if not owned:
        labels['com.docker.compose.service'] = 'ghostfolio'
    def command(args, **kwargs):
        calls.append(args)
        return json.dumps('a' * 64) + '\n' + json.dumps(labels) if 'inspect' in args else ''
    monkeypatch.setattr(wrapper, 'command', command)
    if owned:
        wrapper.remove_owned_worker('owned-name', 'marker')
        assert calls[-1] == ['docker', 'rm', '-f', 'a' * 64]
    else:
        with pytest.raises(RuntimeError):
            wrapper.remove_owned_worker('owned-name', 'marker')
        assert len(calls) == 1


def test_runner_refuses_unarmed_invocation_before_any_network(monkeypatch):
    monkeypatch.delenv('DEGIRO_PERSISTENT_LAB', raising=False)
    with pytest.raises(RuntimeError):
        runner.execute(SimpleNamespace(scenario='synthetic', manifest_sha256='0' * 64))


@pytest.mark.parametrize('name', ['DEGIRO_USERNAME', 'DEGIRO_PASSWORD', 'DEGIRO_TOTP_SECRET', 'GHOST_TOKEN', 'APPRISE_URLS'])
def test_runner_refuses_operator_credentials_before_any_network(monkeypatch, name):
    monkeypatch.setenv('DEGIRO_PERSISTENT_LAB', wrapper.MARKER)
    monkeypatch.setenv(name, 'synthetic-forbidden-value')
    with pytest.raises(RuntimeError):
        runner.execute(SimpleNamespace(scenario='replay', manifest_sha256='0' * 64))
