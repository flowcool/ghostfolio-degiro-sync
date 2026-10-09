"""Offline privacy, exact evidence and isolation checks for the native probe."""
import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys

import pytest
import requests


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('check_interest_contract')


@pytest.fixture
def native(monkeypatch):
    rows = []
    calls = []
    settings = {}
    fault = {}

    def send(session, request, **kwargs):
        assert request.url.startswith('http://192.0.2.1:3333/api/v1/')
        assert kwargs['allow_redirects'] is False and kwargs['timeout'] == (3, 30)
        assert session.trust_env is False
        path = request.url.split('/api/v1/')[1]
        calls.append((request.method, path))
        body = json.loads(request.body) if request.body else None
        status = 200
        if path == 'user':
            result, status = {'authToken': 'LAB_TOKEN_SENTINEL'}, 201
        elif path == 'user/setting':
            assert request.method == 'PUT'
            settings.update(body)
            result = {}
        elif path == 'account' and request.method == 'POST':
            result, status = {'id': 'lab-account'}, 201
        elif path == 'account':
            assert settings['baseCurrency'] == 'EUR'
            result = {'accounts': [{'id': 'lab-account', 'balance': 0,
                'interestInBaseCurrency': fault.get('interest', sum(r['unitPrice'] for r in rows))}]}
        elif path == 'activities':
            stored = [dict(row) for row in rows]
            if fault.get('stored_distribution') and len(stored) >= 2:
                stored[0]['unitPrice'] -= 1
                stored[1]['unitPrice'] += 1
            if fault.get('stored_reverse'):
                stored.reverse()
            result = {'count': len(rows), 'activities': stored}
        elif path.startswith('import'):
            status = 201
            activities = body['activities']
            if any(a[field] < 0 for a in activities for field in ('fee', 'quantity', 'unitPrice')):
                result, status = {}, 400
            else:
                created = [{**a, 'id': 'created-' + a['comment'],
                    'assetProfile': {'symbol': a['symbol'], 'dataSource': 'MANUAL'}}
                    for a in activities if not any(r['comment'] == a['comment'] for r in rows)]
                if not path.endswith('dryRun=true'):
                    rows.extend(created)
                result = {'activities': [{**r, 'fee': fault.get('fee', r['fee'])} for r in created]}
        else:
            pytest.fail('Unexpected lab route')
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(result).encode()
        return response

    monkeypatch.setattr(requests.Session, 'send', send)
    return calls, fault


def test_probe_proves_exact_native_outcomes_without_credential_logging(probe, native, caplog):
    caplog.set_level(logging.DEBUG)
    result = probe.probe('http://192.0.2.1:3333')
    assert result['created'] == 3 and result['repeat_created'] == 0
    assert result['interest_total_eur'] == 20 and result['balance_eur'] == 0
    assert result['negative_quantity_price_fee_rejected'] is True
    assert 'LAB_TOKEN_SENTINEL' not in caplog.text


@pytest.mark.parametrize('field,value', [('fee', 1), ('interest', 0)])
def test_probe_rejects_changed_accepted_evidence_or_aggregation(probe, native, field, value):
    native[1][field] = value
    with pytest.raises(RuntimeError):
        probe.probe('http://192.0.2.1:3333')


@pytest.mark.parametrize('labels,binds,ports', [
    ({'com.docker.compose.project': 'foreign'}, None, None),
    ({'com.docker.compose.project': 'owned'}, ['/production:/data'], None),
    ({'com.docker.compose.project': 'owned'}, None, {'3333/tcp': []}),
])
def test_probe_rejects_foreign_or_exposed_container(probe, monkeypatch, labels, binds, ports):
    info = {'Config': {'Labels': labels}, 'HostConfig': {'Binds': binds, 'PortBindings': ports}}
    monkeypatch.setattr(probe, 'run', lambda *args: json.dumps([info]))
    with pytest.raises(RuntimeError):
        probe.inspect_owned_container('selected-container', 'owned')


def test_probe_rejects_redistributed_stored_amount_with_unchanged_total(probe, native):
    native[1]['stored_distribution'] = True
    with pytest.raises(RuntimeError, match='financial evidence'):
        probe.probe('http://192.0.2.1:3333')


def test_exact_stored_evidence_accepts_reordered_listing(probe, native):
    native[1]['stored_reverse'] = True
    assert probe.probe('http://192.0.2.1:3333')['created'] == 3


def test_compose_project_is_pinned_despite_environment_override(probe, monkeypatch, tmp_path):
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'shared-production')
    assert probe.compose_command('owned-uuid', tmp_path / 'compose.yaml') == [
        'docker', 'compose', '-p', 'owned-uuid', '-f', str(tmp_path / 'compose.yaml')]


def test_optimized_python_retains_isolation_and_evidence_checks(probe):
    program = '''
import json
import check_interest_contract as probe
probe.run = lambda *args: json.dumps([{'Config': {'Labels': {
    'com.docker.compose.project': 'foreign'}},
    'HostConfig': {'Binds': None, 'PortBindings': None}}])
for check in (lambda: probe.ensure(False),
              lambda: probe.inspect_owned_container('selected', 'owned')):
    try:
        check()
    except RuntimeError:
        pass
    else:
        raise SystemExit('Optimized safety check bypassed')
'''
    result = subprocess.run([sys.executable, '-O', '-c', program],
        cwd=Path(probe.__file__).parent, capture_output=True, timeout=10)
    assert result.returncode == 0
