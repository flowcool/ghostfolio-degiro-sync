"""Failed preflight must never reach a GitHub mutation."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import merge_pr as merge


HEAD = 'a' * 40
PROOF = {'ready': True, 'head': HEAD, 'required_checks': 6,
    'review_url': 'https://github.com/flowcool/ghostfolio-degiro-sync/pull/29#issuecomment-123'}


@pytest.fixture
def calls(monkeypatch):
    calls = []
    monkeypatch.setattr(merge, 'check_merge', lambda number: dict(PROOF))

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(merge.subprocess, 'run', run)
    return calls


def test_failed_preflight_makes_zero_merge_calls(calls, monkeypatch):
    def failed(number):
        raise RuntimeError('GitHub merge eligibility is not clean')

    monkeypatch.setattr(merge, 'check_merge', failed)
    with pytest.raises(RuntimeError, match='eligibility'):
        merge.merge_pr(29)
    assert calls == []


@pytest.mark.parametrize('field,value', [('ready', False), ('ready', 1),
    ('head', None), ('head', 'a' * 39), ('required_checks', 0),
    ('required_checks', True), ('review_url', 'https://untrusted.invalid'),
    ('review_url', PROOF['review_url'].replace('/29#', '/30#'))])
def test_malformed_proof_makes_zero_merge_calls(calls, monkeypatch, field, value):
    monkeypatch.setattr(merge, 'check_merge', lambda number: dict(PROOF, **{field: value}))
    with pytest.raises(RuntimeError):
        merge.merge_pr(29)
    assert calls == []


@pytest.mark.parametrize('proof', [None, [], 'ready'])
def test_missing_proof_makes_zero_merge_calls(calls, monkeypatch, proof):
    monkeypatch.setattr(merge, 'check_merge', lambda number: proof)
    with pytest.raises(RuntimeError):
        merge.merge_pr(29)
    assert calls == []


def test_merge_uses_only_live_proven_head_and_bounded_command(calls):
    assert merge.merge_pr(29) == dict(PROOF, merge_command_succeeded=True)
    command, kwargs = calls[0]
    assert command == ['gh', 'pr', 'merge', '29', '--repo', 'github.com/' + merge.REPOSITORY,
        '--merge', '--match-head-commit', HEAD]
    assert kwargs == {'capture_output': True, 'text': True, 'timeout': 120, 'check': False}


@pytest.mark.parametrize('case', ['failure', 'timeout', 'missing_binary'])
def test_merge_failure_returns_no_success_and_hides_transport_output(calls, monkeypatch, capsys, case):
    private = 'PRIVATE_SYNTHETIC_SENTINEL'

    def run(command, **kwargs):
        if case == 'timeout':
            raise subprocess.TimeoutExpired(command, 120, output=private)
        if case == 'missing_binary':
            raise OSError(private)
        return SimpleNamespace(returncode=1, stdout=private, stderr=private)

    monkeypatch.setattr(merge.subprocess, 'run', run)
    monkeypatch.setattr(merge.sys, 'argv', ['merge_pr.py', '29'])
    assert merge.main() == 1
    output = capsys.readouterr()
    assert not output.out and 'inspect GitHub before retrying' in output.err
    assert private not in output.err


def test_cli_returns_selected_proof(calls, monkeypatch, capsys):
    monkeypatch.setattr(merge.sys, 'argv', ['merge_pr.py', '29'])
    assert merge.main() == 0
    assert json.loads(capsys.readouterr().out)['head'] == HEAD


@pytest.mark.parametrize('number', [0, -1, True, 2 ** 31])
def test_invalid_number_never_reaches_preflight(calls, monkeypatch, number):
    monkeypatch.setattr(merge, 'check_merge', lambda number: pytest.fail('Invalid number queried'))
    with pytest.raises(RuntimeError):
        merge.merge_pr(number)
    assert calls == []
