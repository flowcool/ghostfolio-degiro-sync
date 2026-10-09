"""Operator CLI uses environment-only configuration and emits controlled output."""
import pytest

from scripts import recover_degiro


@pytest.mark.parametrize('confirm', [False, True])
def test_recovery_command_defaults_to_preflight(monkeypatch, capsys, confirm):
    environment = {'GHOST_HOST': 'http://localhost:3333', 'GHOST_TOKEN': 'TOKEN-SENTINEL',
        'GHOST_ACCOUNT_ID': 'target-a', 'DEGIRO_ACCOUNT_ID': '123', 'STATE_DIR': '/private/state'}
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('DRY_RUN', '0')
    def recovery(config, *, expected_intent_id, confirm=False):
        assert config == {'ghost_host': environment['GHOST_HOST'], 'ghost_token': environment['GHOST_TOKEN'],
            'target_account': 'target-a', 'source_account': '123', 'state_dir': '/private/state'}
        assert expected_intent_id == 'a' * 32
        return {'matched': 2, 'confirmed': confirm, 'snapshot_sha256': 'f' * 64}
    monkeypatch.setattr(recover_degiro.adapter, 'readback_import_intent', recovery)
    arguments = ['--expected-intent-id', 'a' * 32]
    if confirm:
        arguments.append('--confirm-local-state')
    assert recover_degiro.main(arguments) == 0
    output = capsys.readouterr().out
    assert 'snapshot SHA-256=' + 'f' * 64 in output
    assert ('confirmed locally' if confirm else 'verified; intent retained') in output
    assert 'TOKEN-SENTINEL' not in output and 'a' * 32 not in output


def test_recovery_command_never_prints_private_failure(monkeypatch, capsys):
    def failed(*args, **kwargs):
        raise RuntimeError('TOKEN-SENTINEL PRIVATE-SENTINEL')
    monkeypatch.setattr(recover_degiro.adapter, 'readback_import_intent', failed)
    assert recover_degiro.main(['--expected-intent-id', 'a' * 32]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'TOKEN-SENTINEL' not in output.err and 'PRIVATE-SENTINEL' not in output.err
    assert 'inspect private state' in output.err
