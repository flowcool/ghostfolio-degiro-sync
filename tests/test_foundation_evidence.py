"""Native lab evidence never broadens the existing access contract."""
import json
import logging

import pytest

from ghostfolio_degiro_sync import config, diagnostics, sync
from test_degiro_sync import MAPPING, NOW, QUOTES, TARGET, activity_row, opening_holding, snapshot


def records(caplog):
    return [json.loads(record.message.split('LAB_EVIDENCE ', 1)[1])
        for record in caplog.records if 'LAB_EVIDENCE ' in record.message]


@pytest.mark.parametrize('empty', [False, True])
def test_debug_evidence_is_complete_once_and_info_is_silent(snapshot, caplog, empty):
    snapshot['from_date'], snapshot['to_date'] = '2026-01-01', '2026-01-31'
    body = {'activities': [opening_holding()], 'count': 1}
    cfg = {'source_account': '123', 'target_account': 'target-a', 'dry_run': True}
    if empty:
        selection = sync.select_account_activities(cfg, snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
        body['activities'] += [activity_row(dict(row), str(index)) for index, row in enumerate(selection.selection.proposals)]
        body['count'] = len(body['activities'])
    with caplog.at_level(logging.DEBUG, logger='ghostfolio_degiro_sync'):
        result = sync.synchronize_account(cfg, snapshot, TARGET, body, MAPPING, QUOTES,
            lambda *args: pytest.fail('POST'), lambda *args: pytest.fail('PUT'), now=NOW)
    evidence = records(caplog)
    assert [record['kind'] for record in evidence] == ['window', 'preview', 'cash']
    assert evidence[1]['value'] == result['proposed']
    assert evidence[2]['value'] == {'accountId': 'target-a', 'balance': 12.3, 'currency': 'EUR'}
    assert all(set(record) == {'kind', 'value'} for record in evidence)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger='ghostfolio_degiro_sync'):
        diagnostics.emit_lab_evidence('preview', [])
    assert records(caplog) == []


def test_unavailable_window_and_nonfinite_values_emit_no_fabricated_evidence(caplog):
    with caplog.at_level(logging.DEBUG, logger='ghostfolio_degiro_sync'):
        diagnostics.emit_lab_evidence('cash', {'balance': float('nan')})
        diagnostics.emit_window_evidence({'from_date': None, 'to_date': None})
    assert records(caplog) == []


def test_invalid_log_level_stops_before_broker_and_does_not_echo(monkeypatch, caplog):
    from ghostfolio_degiro_sync import app as command
    monkeypatch.setenv('LOG_LEVEL', 'SECRET')
    monkeypatch.setattr(sync, 'run_sync', lambda *args: pytest.fail('access'))
    assert command.main(['--sync']) == 1
    assert 'SECRET' not in caplog.text


def test_debug_configuration_does_not_enable_third_party_loggers(monkeypatch):
    import ghostfolio_core
    logger = logging.getLogger('urllib3')
    before = (logger.level, logging.getLogger().level, ghostfolio_core.log.level)
    try:
        config.configure_logging({'LOG_LEVEL': 'DEBUG'})
        assert logging.getLogger('ghostfolio_degiro_sync').level == logging.DEBUG
        assert before == (logger.level, logging.getLogger().level, ghostfolio_core.log.level)
    finally:
        config.configure_logging({})
