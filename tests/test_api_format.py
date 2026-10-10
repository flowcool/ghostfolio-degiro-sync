"""Secret-free API contract diagnosis without age-based acceptance or writes."""
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter
from test_degiro_read import broker_http, credentials, response, assert_no_secrets


@pytest.fixture
def snapshot():
    data = yaml.safe_load((Path(__file__).parent / 'fixtures/degiro_contract.yaml').read_text())
    data['cash_movements'] = []
    return data


@pytest.mark.parametrize('year', ['2019', '2026'])
def test_supported_contract_does_not_depend_on_calendar_age(snapshot, year):
    snapshot['transactions'][0]['date'] = year + '-01-02T10:00:00+01:00'
    before = deepcopy(snapshot)
    adapter.check_api_import_format(snapshot)
    assert snapshot == before


@pytest.mark.parametrize('case,reason', [
    ('CASH_FUND_NAV_CHANGE', 'legacy_cash'),
    ('CASH_FUND_TRANSACTION', 'legacy_cash'),
    ('financial', 'financial_schema'),
    ('fx', 'fx_schema'),
    ('transactions', 'unknown'),
    ('cash_movements', 'unknown'),
])
@pytest.mark.parametrize('dry_run', [True, False])
def test_incompatible_formats_block_before_dispatch(snapshot, case, reason, dry_run):
    if reason == 'legacy_cash':
        snapshot['cash_movements'].append({'id': 0, 'type': case})
    elif case == 'financial':
        snapshot['transactions'][0]['price'] = 'CREDENTIAL_SENTINEL'
    elif case == 'fx':
        snapshot['transactions'][0]['fxRate'] = 0
    else:
        snapshot[case] = ['CREDENTIAL_SENTINEL']
    before = deepcopy(snapshot)
    with pytest.raises(RuntimeError) as caught:
        adapter.synchronize_locked({'dry_run': dry_run}, snapshot, {}, {}, {}, {},
            lambda *a: pytest.fail('Import dispatched'), lambda *a: pytest.fail('Cash dispatched'))
    assert str(caught.value) == adapter.API_FORMAT_ERRORS[reason]
    assert 'CREDENTIAL_SENTINEL' not in str(caught.value)
    assert snapshot == before


@pytest.mark.parametrize('field,value', [
    ('feeInBaseCurrency', None), ('price', 'CREDENTIAL_SENTINEL'),
    ('quantity', float('nan')), ('grossFxRate', True),
])
def test_incompatible_fields_are_not_defaulted_or_echoed(snapshot, field, value):
    snapshot['transactions'][0][field] = value
    with pytest.raises(RuntimeError) as caught:
        adapter.check_api_import_format(snapshot)
    assert str(caught.value) == adapter.API_FORMAT_ERRORS['financial_schema']
    assert 'CREDENTIAL_SENTINEL' not in str(caught.value)
    assert snapshot['transactions'][0][field] is value


@pytest.mark.parametrize('field', ['fxRate', 'grossFxRate'])
def test_zero_rate_is_incompatible_not_invented_legacy_version(snapshot, field):
    snapshot['transactions'][0][field] = 0
    with pytest.raises(RuntimeError) as caught:
        adapter.check_api_import_format(snapshot)
    assert str(caught.value) == adapter.API_FORMAT_ERRORS['fx_schema']
    assert snapshot['transactions'][0][field] == 0


@pytest.mark.parametrize('bad', [None, {}, {'transactions': None, 'cash_movements': []},
                                 {'transactions': [None], 'cash_movements': []}])
def test_unknown_history_is_not_called_legacy(bad):
    with pytest.raises(RuntimeError) as caught:
        adapter.check_api_import_format(bad)
    assert str(caught.value) == adapter.API_FORMAT_ERRORS['unknown']


@pytest.mark.parametrize('body', [{}, {'data': {'unexpected': []}}, {'data': {'cashMovements': None}},
                                   {'data': {'cashMovements': ['CREDENTIAL_SENTINEL']}}])
def test_unknown_cash_envelope_is_not_invented_as_empty_or_legacy(body):
    with pytest.raises(RuntimeError) as caught:
        adapter.raw_rows(body, 'cashMovements')
    assert str(caught.value) == adapter.API_FORMAT_ERRORS['unknown']


def test_legacy_reader_error_survives_sanitization_and_logs_out(credentials, monkeypatch, caplog):
    calls = broker_http(monkeypatch, '/accountoverview', response({'data': {'cashMovements': [
        {'id': 0, 'type': 'CASH_FUND_NAV_CHANGE', 'description': 'CREDENTIAL_SENTINEL'}]}}))
    with pytest.raises(RuntimeError) as caught:
        adapter.read_degiro(date(2019, 1, 1), date(2019, 1, 2))
    assert str(caught.value) == adapter.API_FORMAT_ERRORS['legacy_cash']
    assert '/logout;' in calls[-1][0].url
    assert_no_secrets(caplog.text + str(caught.value))
    assert 'CREDENTIAL_SENTINEL' not in caplog.text + str(caught.value)


def test_readonly_cli_reports_legacy_format_without_saving_bad_snapshot(
        credentials, monkeypatch, caplog, tmp_path):
    calls = broker_http(monkeypatch, '/accountoverview', response({'data': {'cashMovements': [
        {'id': 0, 'type': 'CASH_FUND_NAV_CHANGE', 'description': 'CREDENTIAL_SENTINEL'}]}}))
    output = tmp_path / 'snapshot.json'
    assert adapter.main(['--read-only', '--from-date', '2019-01-01',
                         '--to-date', '2019-01-02', '--output', str(output)]) == 1
    assert adapter.API_FORMAT_ERRORS['legacy_cash'] in caplog.text
    assert 'CREDENTIAL_SENTINEL' not in caplog.text
    assert_no_secrets(caplog.text)
    assert not output.exists()
    assert '/logout;' in calls[-1][0].url


@pytest.mark.parametrize('field,value,reason', [
    ('price', 'CREDENTIAL_SENTINEL', 'financial_schema'),
    ('feeInBaseCurrency', None, 'financial_schema'),
    ('fxRate', 0, 'fx_schema'),
])
def test_readonly_cli_rejects_execution_format_before_saving(
        snapshot, credentials, monkeypatch, caplog, tmp_path, field, value, reason):
    snapshot['transactions'][0][field] = value
    snapshot['transactions'][0]['productId'] = 20
    calls = broker_http(monkeypatch, '/transactions', response({'data': snapshot['transactions']}))
    output = tmp_path / 'snapshot.json'
    assert adapter.main(['--read-only', '--from-date', '2026-01-01',
                         '--to-date', '2026-01-02', '--output', str(output)]) == 1
    assert adapter.API_FORMAT_ERRORS[reason] in caplog.text
    assert 'CREDENTIAL_SENTINEL' not in caplog.text
    assert_no_secrets(caplog.text)
    assert not output.exists()
    assert '/logout;' in calls[-1][0].url


@pytest.mark.parametrize('reason', list(adapter.API_FORMAT_ERRORS.values()) + ['CREDENTIAL_SENTINEL'])
def test_sync_cli_exposes_only_fixed_format_diagnostics(monkeypatch, caplog, reason):
    def failed(*args):
        raise RuntimeError(reason)
    monkeypatch.setattr(adapter, 'run_sync', failed)
    assert adapter.main(['--sync']) == 1
    assert 'CREDENTIAL_SENTINEL' not in caplog.text
    if reason in adapter.API_FORMAT_ERRORS.values():
        assert reason in caplog.text
    else:
        assert 'unknown, incomplete or uncertain' in caplog.text
