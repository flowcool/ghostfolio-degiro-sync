"""Cleartext warnings precede credential use without disclosing configuration."""

import logging

import pytest
import requests

import degiro_to_ghostfolio as adapter
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import ghostfolio as ghostfolio_module

from test_degiro_sync import TARGET, response


@pytest.mark.parametrize('host', ['http://ghostfolio:3333', 'http://10.0.0.2:3333',
                                  'https://portfolio.example'])
@pytest.mark.parametrize('exchange', [True, False])
def test_warning_precedes_http_credential_use(monkeypatch, caplog, host, exchange):
    token = 'SYNTHETIC-CREDENTIAL-SENTINEL'
    caplog.set_level(logging.WARNING, logger=diagnostics_module.log.name)
    calls = []

    def send(session, request, **kwargs):
        warnings = [record for record in caplog.records if 'cleartext' in record.message]
        assert len(warnings) == (1 if host.startswith('http:') else 0)
        calls.append(request.method)
        return response({'authToken': token} if exchange else {'activities': []})

    monkeypatch.setattr(requests.Session, 'send', send)
    if exchange:
        assert ghostfolio_module.ghost_exchange_access_token(host, token) == token
    else:
        config = {'ghost_host': host, 'ghost_token': token, 'dry_run': True}
        with ghostfolio_module.ghost_transport(config, TARGET) as session:
            session.get(host + '/api/v1/activities')
    assert calls == ['POST' if exchange else 'GET']
    assert host not in caplog.text
    assert token not in caplog.text
    assert TARGET['id'] not in caplog.text


def test_rejected_http_origin_never_warns_or_sends(monkeypatch, caplog):
    monkeypatch.setattr(requests.Session, 'send',
                        lambda *a, **k: pytest.fail('Rejected origin sent credentials'))
    with pytest.raises(RuntimeError, match='origin policy'):
        ghostfolio_module.ghost_exchange_access_token('http://outside.example', 'SYNTHETIC-TOKEN')
    assert 'cleartext' not in caplog.text
