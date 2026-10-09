"""Synthetic GitHub metadata only; no credentials or real network calls."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import check_pr_merge as preflight


HEAD = 'a' * 40
URL = 'https://github.com/flowcool/ghostfolio-degiro-sync/pull/24#pullrequestreview-100'


def page(nodes, next_cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': next_cursor is not None,
        'endCursor': next_cursor}}


def metadata():
    return {'headRefOid': HEAD, 'state': 'OPEN', 'isDraft': False,
        'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN'}


def review():
    return {'id': 'review-100', 'author': {'login': 'coderabbitai'},
        'state': 'COMMENTED', 'commit': {'oid': HEAD}, 'body': '', 'url': URL,
        'submittedAt': '2026-10-09T12:00:00Z'}


@pytest.fixture
def github(monkeypatch):
    data = {'initial': metadata(), 'final': metadata(), 'base_calls': 0, 'calls': [],
        'reviews': {None: page([review()])},
        'checks': {None: page([
            {'id': 'test-1', '__typename': 'CheckRun', 'name': 'test',
                'isRequired': True, 'status': 'COMPLETED', 'conclusion': 'SUCCESS'},
            {'id': 'rabbit-1', '__typename': 'StatusContext', 'context': 'CodeRabbit',
                'isRequired': False, 'state': 'SUCCESS', 'creator': {'login': 'coderabbitai'}}])},
        'threads': {None: page([])}}

    def query(query, number, deadline, cursor=None):
        assert number == 24
        assert query.startswith('query(') and 'mutation' not in query
        data['calls'].append((query, cursor))
        for connection, fragment in (('reviews', 'reviews(first:'),
                ('threads', 'reviewThreads(first:'), ('checks', 'contexts(first:')):
            if fragment in query:
                result = {'headRefOid': data.get('connection_head', HEAD)}
                body = deepcopy(data[connection][cursor])
                if connection == 'checks':
                    result['commits'] = {'nodes': [{'commit': {'oid': data.get('checks_head', HEAD),
                        'statusCheckRollup': {'contexts': body}}}]}
                else:
                    result['reviews' if connection == 'reviews' else 'reviewThreads'] = body
                return result
        data['base_calls'] += 1
        return deepcopy(data['initial' if data['base_calls'] == 1 else 'final'])

    monkeypatch.setattr(preflight, 'gh_query', query)
    return data


def test_exact_final_review_green_checks_and_complete_threads(github):
    assert preflight.check_merge(24) == {'ready': True, 'head': HEAD,
        'review_url': URL, 'required_checks': 1}
    assert github['base_calls'] == 2
    assert len(github['calls']) == 5


@pytest.mark.parametrize('field,value', [
    ('body', 'Review skipped'), ('body', 'Review in progress'),
    ('body', 'Rate limit exceeded'), ('body', None),
    ('state', 'PENDING'), ('state', 'CHANGES_REQUESTED'), ('state', 'DISMISSED'),
    ('url', 'https://untrusted.invalid/private'), ('submittedAt', None),
    ('submittedAt', '2026-10-09T12:00:00'),
])
def test_incomplete_or_untrusted_review_refuses(github, field, value):
    github['reviews'][None]['nodes'][0][field] = value
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('case', ['missing', 'stale', 'wrong_author', 'summary_only'])
def test_non_review_evidence_is_not_accepted(github, case):
    rows = github['reviews'][None]['nodes']
    if case in ('missing', 'summary_only'):
        rows.clear()
    elif case == 'stale':
        rows[0]['commit']['oid'] = 'b' * 40
    else:
        rows[0]['author']['login'] = 'untrusted'
    with pytest.raises(RuntimeError, match='review of final head missing'):
        preflight.check_merge(24)


def test_newest_final_head_review_is_authoritative(github):
    old = review()
    old.update(id='old-review', state='CHANGES_REQUESTED', submittedAt='2026-10-09T11:00:00Z')
    github['reviews'][None]['nodes'].insert(0, old)
    assert preflight.check_merge(24)['ready']
    github['reviews'][None]['nodes'][1]['state'] = 'CHANGES_REQUESTED'
    with pytest.raises(RuntimeError, match='requests changes'):
        preflight.check_merge(24)


@pytest.mark.parametrize('field,value', [('conclusion', 'FAILURE'),
    ('conclusion', 'SKIPPED'), ('status', 'IN_PROGRESS'), ('isRequired', None)])
def test_required_ci_is_not_optional(github, field, value):
    github['checks'][None]['nodes'][0][field] = value
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('case', ['empty_required', 'missing_rabbit', 'pending_rabbit',
    'wrong_creator', 'duplicate_rabbit', 'wrong_head'])
def test_check_provenance_and_completeness(github, case):
    checks = github['checks'][None]['nodes']
    if case == 'empty_required':
        checks[0]['isRequired'] = False
    elif case == 'missing_rabbit':
        checks.pop()
    elif case == 'pending_rabbit':
        checks[1]['state'] = 'PENDING'
    elif case == 'wrong_creator':
        checks[1]['creator']['login'] = 'untrusted'
    elif case == 'duplicate_rabbit':
        other = deepcopy(checks[1])
        other['id'] = 'rabbit-2'
        checks.append(other)
    else:
        github['checks_head'] = 'b' * 40
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('resolved', [False, None, 'true'])
def test_unresolved_or_malformed_conversation_blocks(github, resolved):
    github['threads'][None]['nodes'].append({'id': 'thread-1', 'isResolved': resolved})
    with pytest.raises(RuntimeError, match='conversation'):
        preflight.check_merge(24)


@pytest.mark.parametrize('connection', ['reviews', 'checks', 'threads'])
def test_every_connection_is_paginated(github, connection):
    first = github[connection][None]
    first['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
    if connection == 'threads':
        first['nodes'] = [{'id': 'thread-1', 'isResolved': True}]
        second = [{'id': 'thread-2', 'isResolved': False}]
    elif connection == 'checks':
        second = [{'id': 'test-2', '__typename': 'CheckRun', 'name': 'core-integrity',
            'isRequired': True, 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
    else:
        second = [review()]
        second[0].update(id='review-101', state='CHANGES_REQUESTED',
            submittedAt='2026-10-09T13:00:00Z')
    github[connection]['next'] = page(second)
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)
    assert any(cursor == 'next' for _, cursor in github['calls'])


@pytest.mark.parametrize('case', ['missing_cursor', 'missing_page_info', 'duplicate_id', 'cycle'])
def test_incomplete_or_repeated_pagination_refuses(github, case):
    first = github['reviews'][None]
    first['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
    if case == 'missing_cursor':
        first['pageInfo']['endCursor'] = None
    elif case == 'missing_page_info':
        del first['pageInfo']
    else:
        other = review()
        if case == 'cycle':
            other.update(id='review-101', submittedAt='2026-10-09T13:00:00Z')
        github['reviews']['next'] = page([other], 'next' if case == 'cycle' else None)
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('case', ['connection_head', 'final_head', 'closed', 'draft',
    'conflict', 'blocked', 'unknown_head'])
def test_changed_head_or_server_ineligibility_refuses(github, case):
    if case == 'connection_head':
        github['connection_head'] = 'b' * 40
    elif case == 'final_head':
        github['final']['headRefOid'] = 'b' * 40
    elif case == 'closed':
        github['final']['state'] = 'CLOSED'
    elif case == 'draft':
        github['initial']['isDraft'] = True
    elif case == 'conflict':
        github['final']['mergeable'] = 'CONFLICTING'
    elif case == 'blocked':
        github['final']['mergeStateStatus'] = 'BLOCKED'
    else:
        github['initial']['headRefOid'] = None
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


def test_query_transport_is_bounded_and_read_only(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {'data': {'repository': {'pullRequest': metadata()}}}))

    monkeypatch.setattr(preflight.subprocess, 'run', run)
    assert preflight.gh_query(preflight.query_for(), 24, preflight.time.monotonic() + 90) == metadata()
    command, kwargs = calls[0]
    assert command[:5] == ['gh', 'api', '--hostname', 'github.com', 'graphql']
    assert command[6].startswith('query=query(') and 'mutation' not in command[6]
    assert command[-2:] == ['-F', 'number=24']
    assert 0 < kwargs['timeout'] <= 20 and kwargs['capture_output'] and not kwargs['check']
    assert 'shell' not in kwargs and all('token' not in arg.lower() for arg in command)


def test_check_union_selects_ids_only_inside_concrete_fragments():
    query = preflight.query_for('checks')
    assert 'nodes { __typename ... on CheckRun { id ' in query
    assert '... on StatusContext { id ' in query
    assert 'nodes { id __typename' not in query


@pytest.mark.parametrize('case', ['failure', 'timeout', 'bad_json', 'graphql_error', 'missing_pr'])
def test_transport_failure_diagnostics_are_private(monkeypatch, capsys, case):
    secret = 'PRIVATE_SYNTHETIC_SENTINEL'

    def run(command, **kwargs):
        if case == 'timeout':
            raise subprocess.TimeoutExpired(command, 20, output=secret, stderr=secret)
        output = {'failure': secret, 'bad_json': secret,
            'graphql_error': json.dumps({'errors': [{'message': secret}]}),
            'missing_pr': json.dumps({'data': {'repository': {'pullRequest': None}}})}[case]
        return SimpleNamespace(returncode=1 if case == 'failure' else 0,
            stdout=output, stderr=secret)

    monkeypatch.setattr(preflight.subprocess, 'run', run)
    monkeypatch.setattr(preflight.sys, 'argv', ['check_pr_merge.py', '24'])
    assert preflight.main() == 1
    output = capsys.readouterr()
    assert 'Preflight blocked:' in output.err and not output.out
    assert secret not in output.err


def test_pagination_budget_is_a_refusal_not_truncation(github):
    for index in range(10):
        row = review()
        row['id'] = 'review-' + str(index)
        github['reviews'][None if index == 0 else str(index)] = page([row], str(index + 1))
    with pytest.raises(RuntimeError, match='page budget'):
        preflight.check_merge(24)


def test_deadline_exhaustion_makes_no_subprocess_call(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Expired preflight attempted a subprocess')

    monkeypatch.setattr(preflight.subprocess, 'run', forbidden)
    with pytest.raises(RuntimeError, match='time budget'):
        preflight.gh_query(preflight.query_for(), 24, preflight.time.monotonic() - 1)


@pytest.mark.parametrize('number', [0, -1, True, 2 ** 31])
def test_invalid_number_never_reaches_github(github, number):
    with pytest.raises(RuntimeError, match='number'):
        preflight.check_merge(number)
    assert not github['calls']


def test_cli_success_outputs_only_selected_merge_evidence(github, monkeypatch, capsys):
    monkeypatch.setattr(preflight.sys, 'argv', ['check_pr_merge.py', '24'])
    assert preflight.main() == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {'ready': True, 'head': HEAD,
        'review_url': URL, 'required_checks': 1}


def test_pr_template_preserves_one_body_and_external_review_contract():
    root = Path(__file__).resolve().parents[1]
    body = (root / '.github/pull_request_template.md').read_text()
    for section in ('Summary', 'Behavior', 'Release impact', 'Evidence',
            'Verification', 'Merge Danger', 'AI assistance', 'CodeRabbit review'):
        assert body.count('## ' + section + '\n') == 1
    assert 'managed externally by Florent' in body
    assert '@coderabbitai' not in body and 'request another incremental pass' not in body
    assert 'check_pr_merge.py' in body and '--match-head-commit' in body
    assert '.github/pull_request_template.md' in (root / 'AGENTS.md').read_text()
