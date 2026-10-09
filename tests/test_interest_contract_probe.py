"""Offline privacy, exact evidence and isolation checks for the native probe."""
import importlib
import json
import logging
from pathlib import Path

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
            result = {'count': len(rows), 'activities': rows}
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
    with pytest.raises((RuntimeError, AssertionError)):
        probe.probe('http://192.0.2.1:3333')


@pytest.mark.parametrize('labels,binds,ports', [
    ({'com.docker.compose.project': 'foreign'}, None, None),
    ({'com.docker.compose.project': 'owned'}, ['/production:/data'], None),
    ({'com.docker.compose.project': 'owned'}, None, {'3333/tcp': []}),
])
def test_probe_rejects_foreign_or_exposed_container(probe, monkeypatch, labels, binds, ports):
    info = {'Config': {'Labels': labels}, 'HostConfig': {'Binds': binds, 'PortBindings': ports}}
    monkeypatch.setattr(probe, 'run', lambda *args: json.dumps([info]))
    with pytest.raises(AssertionError):
        probe.inspect_owned_container('selected-container', 'owned')
