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
    return {'id': 'review-100', 'author': {'login': 'coderabbitai'},
        'state': 'COMMENTED', 'commit': {'oid': HEAD}, 'body': '', 'url': URL,
        'submittedAt': '2026-10-09T12:00:00Z'}


def coverage_comment():
    coverage = {'sourceCommitId': HEAD, 'coveredCommitId': HEAD, 'kind': 'reviewed'}
    return {'id': 'comment-200', 'author': {'login': 'coderabbitai', '__typename': 'Bot'},
        'url': COMMENT_URL, 'createdAt': '2026-10-09T12:00:00Z',
        'updatedAt': '2026-10-09T13:00:00Z',
        'body': '<!-- final_review_risk_start -->\n'
            '<!-- final_review_risk_coverage:' + json.dumps(coverage) + ' -->\n'
            '<!-- final_review_risk_end -->'}


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
        'threads': {None: page([])}}

    def query(query, number, deadline, cursor=None):
        assert number == 24
        assert query.startswith('query(') and 'mutation' not in query
        data['calls'].append((query, cursor))
        for connection, fragment in (('reviews', 'reviews(first:'),
                ('comments', 'comments(first:'),
                ('threads', 'reviewThreads(first:'), ('checks', 'contexts(first:')):
            if fragment in query:
                result = {'headRefOid': data.get('connection_head', HEAD)}
                body = deepcopy(data[connection][cursor])
                if connection == 'checks':
                    result['commits'] = {'nodes': [{'commit': {'oid': data.get('checks_head', HEAD),
                        'statusCheckRollup': {'contexts': body}}}]}
                else:
                    result[{'reviews': 'reviews', 'comments': 'comments',
                        'threads': 'reviewThreads'}[connection]] = body
                return result
        data['base_calls'] += 1
        return deepcopy(data['initial' if data['base_calls'] == 1 else 'final'])

    monkeypatch.setattr(preflight, 'gh_query', query)
    return data


def test_authenticated_final_head_incremental_comment_is_completed_evidence(github):
    github['reviews'][None]['nodes'][0]['commit']['oid'] = 'b' * 40
    github['comments'][None]['nodes'] = [coverage_comment()]
    assert preflight.check_merge(24)['review_url'] == COMMENT_URL


@pytest.mark.parametrize('case', ['wrong_author', 'human_author', 'missing_author',
    'stale_source', 'stale_covered', 'not_reviewed', 'duplicate_marker', 'bad_json',
    'duplicate_field', 'extra_field', 'invalid_sha', 'missing_start', 'missing_end',
    'outside_section', 'rate_limited', 'skipped', 'paused', 'in_progress',
    'progress_marker', 'wrong_url', 'wrong_pr', 'bad_updated', 'naive_time',
    'before_created', 'before_formal', 'missing_body', 'summary_only'])
def test_comment_evidence_fails_closed(github, case):
    github['reviews'][None]['nodes'][0]['commit']['oid'] = 'b' * 40
    comment = coverage_comment()
    github['comments'][None]['nodes'] = [comment]
    if case == 'wrong_author':
        comment['author']['login'] = 'untrusted'
    elif case == 'human_author':
        comment['author']['__typename'] = 'User'
    elif case == 'missing_author':
        comment['author'] = None
    elif case in ('stale_source', 'stale_covered', 'not_reviewed', 'extra_field', 'invalid_sha'):
        fields = {'sourceCommitId': HEAD, 'coveredCommitId': HEAD, 'kind': 'reviewed'}
        if case == 'stale_source': fields['sourceCommitId'] = 'b' * 40
        elif case == 'stale_covered': fields['coveredCommitId'] = 'b' * 40
        elif case == 'not_reviewed': fields['kind'] = 'reused'
        elif case == 'extra_field': fields['unknown'] = True
        else: fields['coveredCommitId'] = 'invalid'
        comment['body'] = comment['body'].replace(
            json.dumps({'sourceCommitId': HEAD, 'coveredCommitId': HEAD, 'kind': 'reviewed'}),
            json.dumps(fields))
    elif case == 'duplicate_marker':
        comment['body'] += '\n' + comment['body']
    elif case == 'bad_json':
        comment['body'] = comment['body'].replace('"kind": "reviewed"', '"kind": invalid')
    elif case == 'duplicate_field':
        comment['body'] = comment['body'].replace('"kind": "reviewed"',
            '"kind": "pending", "kind": "reviewed"')
    elif case in ('missing_start', 'missing_end'):
        marker = 'start' if case == 'missing_start' else 'end'
        comment['body'] = comment['body'].replace('<!-- final_review_risk_' + marker + ' -->', '')
    elif case == 'outside_section':
        comment['body'] = comment['body'].replace('<!-- final_review_risk_start -->\n', '')
        comment['body'] += '\n<!-- final_review_risk_start -->'
    elif case in ('rate_limited', 'skipped', 'paused', 'in_progress', 'progress_marker'):
        comment['body'] += {'rate_limited': '\nRate limit exceeded', 'skipped': '\nReview skipped',
            'paused': '\nReview paused', 'in_progress': '\nReview in progress',
            'progress_marker': '\n<!-- review_in_progress -->'}[case]
    elif case in ('wrong_url', 'wrong_pr'):
        comment['url'] = 'https://untrusted.invalid' if case == 'wrong_url' else COMMENT_URL.replace('/24#', '/25#')
    elif case in ('bad_updated', 'naive_time', 'before_created', 'before_formal'):
        comment['updatedAt'] = {'bad_updated': None, 'naive_time': '2026-10-09T13:00:00',
            'before_created': '2026-10-09T11:00:00Z', 'before_formal': '2026-10-09T12:30:00Z'}[case]
        if case == 'before_formal':
            github['reviews'][None]['nodes'][0]['submittedAt'] = '2026-10-09T14:00:00Z'
    elif case == 'missing_body':
        comment['body'] = None
    else:
        comment['body'] = 'Walkthrough only; no actionable comments.'
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


@pytest.mark.parametrize('exact', [False, True])
@pytest.mark.parametrize('state', ['CHANGES_REQUESTED', 'PENDING', 'DISMISSED'])
def test_comment_does_not_override_formal_review_refusal(github, exact, state):
    row = github['reviews'][None]['nodes'][0]
    row['state'] = state
    if not exact:
        row['commit']['oid'] = 'b' * 40
    github['comments'][None]['nodes'] = [coverage_comment()]
    with pytest.raises(RuntimeError):
        preflight.check_merge(24)


def test_comment_pagination_and_multiple_final_head_evidence_are_not_truncated(github):
    github['reviews'][None]['nodes'].clear()
    github['comments'][None] = page([coverage_comment()], 'next')
    other = coverage_comment()
    other['id'] = 'comment-201'
    other['url'] = COMMENT_URL.replace('-200', '-201')
    github['comments']['next'] = page([other])
    with pytest.raises(RuntimeError, match='ambiguous'):
        preflight.check_merge(24)
    assert any(cursor == 'next' for _, cursor in github['calls'])


def test_comment_pagination_can_find_final_coverage_after_stale_comment(github):
    github['reviews'][None]['nodes'].clear()
    first = coverage_comment()
    first['body'] = first['body'].replace(HEAD, 'b' * 40)
    github['comments'][None] = page([first], 'next')
    second = coverage_comment()
    second['id'] = 'comment-201'
    github['comments']['next'] = page([second])
    assert preflight.check_merge(24)['review_url'] == COMMENT_URL


def test_successful_comment_evidence_does_not_bypass_required_ci(github):
    github['reviews'][None]['nodes'].clear()
    github['comments'][None]['nodes'] = [coverage_comment()]
    github['checks'][None]['nodes'][0]['conclusion'] = 'FAILURE'
    with pytest.raises(RuntimeError, match='Required check'):
        preflight.check_merge(24)


@pytest.mark.parametrize('change', ['deleted', 'edited', 'formal_veto'])
def test_comment_proof_changed_during_preflight_is_refused(github, monkeypatch, change):
    github['reviews'][None]['nodes'].clear()
    github['comments'][None]['nodes'] = [coverage_comment()]
    original = preflight.gh_query

    def query(*args, **kwargs):
        result = original(*args, **kwargs)
        if 'contexts(first:' in args[0]:
            if change == 'deleted':
                github['comments'][None]['nodes'].clear()
            elif change == 'edited':
                github['comments'][None]['nodes'][0]['body'] += '\nUpdated concern'
            else:
                veto = review()
                veto.update(state='CHANGES_REQUESTED', submittedAt='2026-10-09T14:00:00Z')
                github['reviews'][None]['nodes'] = [veto]
        return result

    monkeypatch.setattr(preflight, 'gh_query', query)
    with pytest.raises(RuntimeError, match='evidence changed'):
        preflight.check_merge(24)


def test_exact_final_review_green_checks_and_complete_threads(github):
    assert preflight.check_merge(24) == {'ready': True, 'head': HEAD,
        'review_url': URL, 'required_checks': 1}
    assert github['base_calls'] == 2
    assert len(github['calls']) == 5


@pytest.mark.parametrize('comment', [False, True])
@pytest.mark.parametrize('fence', ['```', '~~~~'])
def test_quoted_policy_is_not_a_review_status_notice(github, comment, fence):
    policy = '\n' + fence + 'text\nSkipped, pending or rate-limited reviews are not evidence.\n' + fence
    if comment:
        github['reviews'][None]['nodes'].clear()
        row = coverage_comment()
        row['body'] += policy
        github['comments'][None]['nodes'] = [row]
    else:
        github['reviews'][None]['nodes'][0]['body'] += policy
    assert preflight.check_merge(24)['ready']


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
