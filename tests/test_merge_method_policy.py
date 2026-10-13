"""Disabled or uncertain GitHub method policy never authorizes a merge."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import merge_pr as merge


HEAD = 'a' * 40


@pytest.fixture
def policy(monkeypatch):
    records = {
        'repos/' + merge.REPOSITORY: {
            'allow_merge_commit': True, 'allow_squash_merge': True, 'allow_rebase_merge': True},
        'repos/' + merge.REPOSITORY + '/pulls/29': {
            'base': {'ref': 'main', 'repo': {'full_name': merge.REPOSITORY}},
            'head': {'sha': HEAD}, 'state': 'open', 'draft': False},
        'repos/' + merge.REPOSITORY + '/rules/branches/main': [
            {'type': 'pull_request', 'parameters': {'allowed_merge_methods': list(merge.METHODS)}}],
    }
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[:6] == ['gh', 'api', '--hostname', 'github.com', '--method', 'GET']
        assert kwargs['timeout'] == 20 and kwargs['check'] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps(records[command[-1]]))

    monkeypatch.setattr(merge.subprocess, 'run', run)
    return records, calls


@pytest.mark.parametrize('method', merge.METHODS)
def test_allowed_methods_use_read_only_effective_base_policy(policy, method):
    assert merge.check_merge_method(29, method, HEAD) == 'main'
    assert len(policy[1]) == 3


@pytest.mark.parametrize('case', ['repository', 'branch', 'intersecting_rules', 'linear_history'])
def test_repository_and_every_effective_rule_must_allow_method(policy, case):
    records, calls = policy
    method = 'merge' if case == 'linear_history' else 'squash'
    rules = records['repos/' + merge.REPOSITORY + '/rules/branches/main']
    if case == 'repository':
        records['repos/' + merge.REPOSITORY]['allow_squash_merge'] = False
    elif case == 'branch':
        rules[0]['parameters']['allowed_merge_methods'] = ['merge']
    elif case == 'intersecting_rules':
        rules.append({'type': 'pull_request', 'parameters': {'allowed_merge_methods': ['rebase']}})
    else:
        rules.append({'type': 'required_linear_history'})
    with pytest.raises(RuntimeError, match='disabled'):
        merge.check_merge_method(29, method, HEAD)
    assert all(command[1] == 'api' for command in calls)


def test_base_branch_is_encoded_and_need_not_be_default(policy):
    records, calls = policy
    records['repos/' + merge.REPOSITORY + '/pulls/29']['base']['ref'] = 'release/v2'
    records['repos/' + merge.REPOSITORY + '/rules/branches/release%2Fv2'] = []
    assert merge.check_merge_method(29, 'rebase', HEAD) == 'release/v2'
    assert calls[-1][-1].endswith('/release%2Fv2')


@pytest.mark.parametrize('case', ['repository', 'pull', 'head', 'base_repository', 'closed',
    'rules', 'parameters', 'unknown_method'])
def test_incomplete_or_changed_policy_blocks_merge(policy, case):
    records, _ = policy
    repository = records['repos/' + merge.REPOSITORY]
    pull = records['repos/' + merge.REPOSITORY + '/pulls/29']
    rules = records['repos/' + merge.REPOSITORY + '/rules/branches/main']
    if case == 'repository':
        repository['allow_squash_merge'] = 1
    elif case == 'pull':
        del pull['base']
    elif case == 'head':
        pull['head']['sha'] = 'b' * 40
    elif case == 'base_repository':
        pull['base']['repo']['full_name'] = 'other/repository'
    elif case == 'closed':
        pull['state'] = 'closed'
    elif case == 'rules':
        records['repos/' + merge.REPOSITORY + '/rules/branches/main'] = None
    elif case == 'parameters':
        del rules[0]['parameters']
    else:
        rules[0]['parameters']['allowed_merge_methods'] = ['auto']
    with pytest.raises(RuntimeError):
        merge.check_merge_method(29, 'squash', HEAD)


@pytest.mark.parametrize('case', ['failure', 'malformed', 'timeout', 'missing_binary'])
def test_unavailable_policy_hides_response_and_never_merges(monkeypatch, case):
    private = 'PRIVATE_SYNTHETIC_SENTINEL'
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if case == 'timeout':
            raise subprocess.TimeoutExpired(command, 20, output=private)
        if case == 'missing_binary':
            raise OSError(private)
        return SimpleNamespace(returncode=1 if case == 'failure' else 0, stdout=private)

    monkeypatch.setattr(merge.subprocess, 'run', run)
    with pytest.raises(RuntimeError) as error:
        merge.check_merge_method(29, 'squash', HEAD)
    assert private not in str(error.value)
    assert len(calls) == 1 and calls[0][1] == 'api'
