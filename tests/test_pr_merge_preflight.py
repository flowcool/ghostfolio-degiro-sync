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
COMMENT_URL = 'https://github.com/flowcool/ghostfolio-degiro-sync/pull/24#issuecomment-200'


def page(nodes, next_cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': next_cursor is not None,
        'endCursor': next_cursor}}


def metadata():
    return {'headRefOid': HEAD, 'state': 'OPEN', 'isDraft': False,
        'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN'}


def review():
    return {'id': 'review-100', 'author': {'login': 'pullfrog', '__typename': 'Bot'},
        'state': 'COMMENTED', 'commit': {'oid': HEAD}, 'body': 'Review complete: no blockers.', 'url': URL,
        'submittedAt': '2026-10-09T12:00:00Z'}


@pytest.fixture
def github(monkeypatch):
    data = {'initial': metadata(), 'final': metadata(), 'base_calls': 0, 'calls': [],
        'reviews': {None: page([review()])},
        'comments': {None: page([])},
        'checks': {None: page([
            {'id': 'test-1', '__typename': 'CheckRun', 'name': 'test',
                'isRequired': True, 'status': 'COMPLETED', 'conclusion': 'SUCCESS'},
            {'id': 'rabbit-1', '__typename': 'StatusContext', 'context': 'CodeRabbit',
                'isRequired': False, 'state': 'SUCCESS', 'creator': {'login': 'coderabbitai'}}])},
        'threads': {None: page([])},
        'files': {None: page([{'path': 'scripts/check_pr_merge.py'}])},
        'parents': ['e' * 40, 'c' * 40], 'base_tip': 'c' * 40,
        'signature': {'isValid': True, 'signer': {'login': 'web-flow'}}}

    def query(query, number, deadline, cursor=None):
        assert number == 24
        assert query.startswith('query(') and 'mutation' not in query
        data['calls'].append((query, cursor))
        if 'parents(first:' in query:
            return {'headRefOid': HEAD, 'commits': {'nodes': [{'commit': {'oid': HEAD,
                'signature': data['signature'],
                'parents': {'nodes': [{'oid': oid} for oid in data['parents']]}}}]},
                'baseRef': {'target': {'oid': data['base_tip']}}}
        for connection, fragment in (('reviews', 'reviews(first:'),
                ('comments', 'comments(first:'),
                ('threads', 'reviewThreads(first:'), ('checks', 'contexts(first:'),
                ('files', 'files(first:')):
            if fragment in query:
                result = {'headRefOid': data.get('connection_head', HEAD)}
                body = deepcopy(data[connection][cursor])
                if connection == 'checks':
                    result['commits'] = {'nodes': [{'commit': {'oid': data.get('checks_head', HEAD),
                        'statusCheckRollup': {'contexts': body}}}]}
                else:
                    result[{'reviews': 'reviews', 'comments': 'comments', 'files': 'files',
                        'threads': 'reviewThreads'}[connection]] = body
                return result
        data['base_calls'] += 1
        return deepcopy(data['initial' if data['base_calls'] == 1 else 'final'])

    monkeypatch.setattr(preflight, 'gh_query', query)
    return data


def test_exact_final_review_green_checks_and_complete_threads(github):
    assert preflight.check_merge(24) == {'ready': True, 'head': HEAD,
        'review_url': URL, 'required_checks': 1, 'docs_only': False}
    assert github['base_calls'] == 2
    assert len(github['calls']) == 7


@pytest.mark.parametrize('notice', ['Review skipped', 'Review paused',
    'Review in progress', 'Rate limit exceeded'])
def test_actual_notice_is_not_hidden_by_context_quotation(github, notice):
    github['reviews'][None]['nodes'][0]['body'] = (
        '```text\nrate-limited reviews are not evidence\n```\n' + notice)
    with pytest.raises(RuntimeError, match='not evidence'):
        preflight.check_merge(24)


@pytest.mark.parametrize('notice', ['Review skipped', 'Review in progress', 'Rate limit exceeded'])
def test_real_notice_inside_complete_fence_still_refuses(github, notice):
    github['reviews'][None]['nodes'][0]['body'] = '```text\n' + notice + '\n```'
    with pytest.raises(RuntimeError, match='not evidence'):
        preflight.check_merge(24)


@pytest.mark.parametrize('closing', ['', '~~~', '``', '```invalid'])
def test_incomplete_or_mismatched_quote_keeps_status_detection(github, closing):
    github['reviews'][None]['nodes'][0]['body'] = '```text\nReview skipped\n' + closing
    with pytest.raises(RuntimeError, match='not evidence'):
        preflight.check_merge(24)


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
        'review_url': URL, 'required_checks': 1, 'docs_only': False}


def docs_only_pr(github):
    github['files'][None] = page([{'path': 'docs/a.md'}, {'path': 'openspec/x/spec.txt'},
        {'path': 'README.md'}])
    github['reviews'][None]['nodes'] = []
    github['checks'][None]['nodes'] = github['checks'][None]['nodes'][:1]


def test_docs_only_pr_is_ready_without_reviewer_evidence(github):
    docs_only_pr(github)
    assert preflight.check_merge(24) == {'ready': True, 'head': HEAD, 'review_url': None,
        'required_checks': 1, 'docs_only': True}


@pytest.mark.parametrize('state', ['PENDING', 'FAILURE'])
def test_docs_only_ignores_coderabbit_status_in_any_state(github, state):
    docs_only_pr(github)
    github['checks'][None]['nodes'].append({'id': 'rabbit-1', '__typename': 'StatusContext',
        'context': 'CodeRabbit', 'isRequired': False, 'state': state,
        'creator': {'login': 'someone'}})
    assert preflight.check_merge(24)['docs_only'] is True


@pytest.mark.parametrize('case', ['thread', 'check'])
def test_docs_only_still_requires_threads_and_checks(github, case):
    docs_only_pr(github)
    if case == 'thread':
        github['threads'][None]['nodes'].append({'id': 'thread-1', 'isResolved': False})
    else:
        github['checks'][None]['nodes'][0]['conclusion'] = 'FAILURE'
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


def test_docs_only_with_one_non_doc_path_needs_pullfrog(github):
    docs_only_pr(github)
    github['files'][None]['nodes'].append({'path': 'scripts/merge_pr.py'})
    with pytest.raises(RuntimeError, match='Pullfrog review of final head missing'):
        preflight.check_merge(24)


def test_empty_file_list_is_not_docs_only(github):
    docs_only_pr(github)
    github['files'][None] = page([])
    with pytest.raises(RuntimeError, match='Pullfrog'):
        preflight.check_merge(24)


@pytest.mark.parametrize('case', ['missing_cursor', 'repeated_path', 'unpaged_next'])
def test_incomplete_files_pagination_refuses_even_for_docs(github, case):
    docs_only_pr(github)
    first = github['files'][None]
    if case == 'missing_cursor':
        first['pageInfo'] = {'hasNextPage': True, 'endCursor': None}
    elif case == 'repeated_path':
        first['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
        github['files']['next'] = page([{'path': 'docs/a.md'}])
    else:
        first['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
        github['files']['next'] = page([{'path': 'src/code.py'}])
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('kind', ['Bot', 'User'])
def test_only_pullfrog_bot_is_authoritative(github, kind):
    github['reviews'][None]['nodes'][0]['author']['__typename'] = kind
    if kind == 'Bot':
        assert preflight.check_merge(24)['ready']
    else:
        with pytest.raises(RuntimeError, match='review of final head missing'):
            preflight.check_merge(24)


@pytest.mark.parametrize('name', ['CodeRabbit', 'pullfrog-approval', 'other-ci'])
def test_only_retired_reviewer_and_sticky_approval_status_are_ignored(github, name):
    github['checks'][None]['nodes'].append({'id': 'extra', '__typename': 'StatusContext',
        'context': name, 'state': 'FAILURE', 'isRequired': False})
    if name in ('CodeRabbit', 'pullfrog-approval'):
        assert preflight.check_merge(24)['ready']
    else:
        with pytest.raises(RuntimeError, match='CI check'):
            preflight.check_merge(24)


@pytest.mark.parametrize('case', ['empty_required', 'wrong_head'])
def test_check_provenance_and_completeness(github, case):
    if case == 'empty_required':
        github['checks'][None]['nodes'][0]['isRequired'] = False
    else:
        github['checks_head'] = 'b' * 40
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


def test_review_evidence_changed_during_preflight_is_refused(github, monkeypatch):
    original = preflight.gh_query
    calls = 0

    def query(*args, **kwargs):
        nonlocal calls
        if 'reviews(first:' in args[0]:
            calls += 1
            if calls == 2:
                github['reviews'][None]['nodes'][0]['body'] = 'Changed review'
        return original(*args, **kwargs)

    monkeypatch.setattr(preflight, 'gh_query', query)
    with pytest.raises(RuntimeError, match='evidence changed'):
        preflight.check_merge(24)


def test_pr_template_preserves_guarded_merge_contract():
    root = Path(__file__).resolve().parents[1]
    body = (root / '.github/pull_request_template.md').read_text()
    for section in ('Summary', 'Behavior', 'Release impact', 'Evidence',
            'Verification', 'Merge Danger', 'AI assistance', 'Pullfrog review'):
        assert body.count('## ' + section + '\n') == 1
    assert 'check_pr_merge.py' in body and '--match-head-commit' in body
    assert '.github/pull_request_template.md' in (root / 'AGENTS.md').read_text()


@pytest.mark.parametrize('earlier', [None, 'CHANGES_REQUESTED', 'COMMENTED'])
def test_reply_reviews_neither_establish_coverage_nor_hide_a_veto(github, earlier):
    reply = review()
    reply.update(id='reply', body='', submittedAt='2026-10-09T13:00:00Z')
    github['reviews'][None]['nodes'] = [reply]
    if earlier:
        summary = review()
        summary['state'] = earlier
        github['reviews'][None]['nodes'].insert(0, summary)
    if earlier == 'COMMENTED':
        assert preflight.check_merge(24)['review_url'] == URL
    else:
        with pytest.raises(RuntimeError):
            preflight.check_merge(24)
