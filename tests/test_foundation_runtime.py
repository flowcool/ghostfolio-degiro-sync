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
