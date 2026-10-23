"""Approved settings/result boundary; all inputs are synthetic."""

from dataclasses import FrozenInstanceError

import pytest


def settings_values():
    return {"ghost_host": "https://portfolio.example", "ghost_token": "SECRET",
        "source_account": "123", "target_account": "target", "dry_run": True,
        "sync_mode": "rolling", "state_dir": "/state", "cutover_manifest": None,
        "cutover_sha256": None}


def test_settings_are_validated_immutable_and_hide_credentials():
    from ghostfolio_degiro_sync.config import parse_settings, runtime_config
    values = settings_values()
    settings = parse_settings(values)
    assert settings.source_account == "123" and settings.dry_run is True
    assert "SECRET" not in repr(settings)
    assert runtime_config(settings) == values
    values["ghost_token"] = "CHANGED"
    assert runtime_config(settings)["ghost_token"] == "SECRET"
    with pytest.raises(FrozenInstanceError):
        settings.dry_run = False


@pytest.mark.parametrize("key,value", [("dry_run", 1), ("sync_mode", "unknown"),
    ("source_account", "0"), ("target_account", "../SECRET"),
    ("ghost_host", "https://SECRET@portfolio.example"),
    ("ghost_token", "SECRET\nHEADER"), ("state_dir", 42),
    ("cutover_sha256", "SECRET")])
def test_malformed_settings_fail_without_echoing_external_values(key, value):
    from ghostfolio_degiro_sync.config import parse_settings
    values = settings_values()
    values[key] = value
    with pytest.raises(RuntimeError) as failure:
        parse_settings(values)
    assert "SECRET" not in str(failure.value)


def test_settings_preserve_one_verbatim_credential():
    from ghostfolio_degiro_sync.config import parse_settings, runtime_config
    values = settings_values()
    values.update(ghost_token=None, ghost_access_token=" SECURITY SECRET ")
    settings = parse_settings(values)
    assert "SECRET" not in repr(settings)
    assert runtime_config(settings)["ghost_access_token"] == " SECURITY SECRET "
    values["ghost_token"] = "BEARER SECRET"
    with pytest.raises(RuntimeError):
        parse_settings(values)


def test_selection_result_is_an_immutable_record():
    from ghostfolio_degiro_sync.models import SelectionResult
    result = SelectionResult(proposals=(), rejected=(), deferred=(), holdings=())
    assert result.proposals == ()
    with pytest.raises(FrozenInstanceError):
        result.proposals = ()


@pytest.mark.parametrize('mode', [None, '', ' ', '1', ' TRUE ', 'yes', 'ON'])
def test_simulation_policy_defaults_and_normalizes(mode):
    from ghostfolio_degiro_sync.config import simulation_policy
    values = {'TZ': 'Europe/Zurich'}
    if mode is not None:
        values['DRY_RUN'] = mode
    assert simulation_policy(values) == (True, False)


@pytest.mark.parametrize('tz', [None, '', 'SECRET/invalid'])
def test_explicit_live_without_valid_timezone_forces_preview(tz):
    from ghostfolio_degiro_sync.config import simulation_policy
    values = {'DRY_RUN': '  FALSE '}
    if tz is not None:
        values['TZ'] = tz
    assert simulation_policy(values) == (True, True)


def test_invalid_simulation_value_never_echoes_input():
    from ghostfolio_degiro_sync.config import simulation_policy
    with pytest.raises(RuntimeError, match='Invalid DRY_RUN') as failure:
        simulation_policy({'DRY_RUN': 'SECRET', 'TZ': 'Europe/Zurich'})
    assert 'SECRET' not in str(failure.value)


@pytest.mark.parametrize('failed', [False, True])
def test_forced_preview_sends_one_summary_with_failure_precedence(monkeypatch, failed):
    from ghostfolio_degiro_sync import app as command
    from ghostfolio_degiro_sync import notify, sync
    monkeypatch.setenv('DRY_RUN', '0')
    monkeypatch.delenv('TZ', raising=False)
    monkeypatch.setenv('APPRISE_URLS', '["json://notify.invalid/hook"]')
    calls = []
    monkeypatch.setattr(notify, 'send_notification', lambda *args: calls.append(args) or 'sent')
    def run(*args):
        if failed:
            raise RuntimeError('SECRET')
        return {'dry_run': True, 'proposed': [], 'accepted': [], 'rolling_verified': True}
    monkeypatch.setattr(sync, 'run_sync', run)
    assert command.main(['--sync']) == int(failed)
    assert len(calls) == 1
    assert ('run failed' if failed else 'simulation forced') in calls[0][1]
    assert 'SECRET' not in calls[0][2]
    if not failed:
        assert 'TZ' in calls[0][2]


def test_blank_mode_warns_once_even_if_configuration_fails(monkeypatch, caplog):
    from ghostfolio_degiro_sync import app as command
    monkeypatch.setenv('DRY_RUN', '  ')
    monkeypatch.delenv('GHOST_HOST', raising=False)
    monkeypatch.setenv('APPRISE_URLS', '')
    assert command.main(['--sync']) == 1
    assert caplog.text.count('DRY_RUN not set: simulation, nothing written') == 1


@pytest.mark.parametrize('path,method,seconds', [('/api/v1/account', 'GET', 120),
    ('/api/v1/account/target-a', 'GET', 120), ('/api/v1/activities', 'GET', 60),
    ('/api/v1/import', 'POST', 60), ('/api/v1/account/target-a', 'PUT', 30)])
def test_transport_uses_operation_timeout(monkeypatch, path, method, seconds):
    import requests
    from ghostfolio_degiro_sync.ghostfolio import ghost_transport
    from test_degiro_sync import TARGET, response, transport_config
    def send(session, request, **options):
        assert options['timeout'] == (10, seconds)
        return response(TARGET)
    monkeypatch.setattr(requests.Session, 'send', send)
    with ghost_transport(transport_config(False), TARGET) as session:
        session.request(method, 'http://localhost:3333' + path)
