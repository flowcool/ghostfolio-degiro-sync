"""Read-only, exact-head GitHub merge preflight; never merges or triggers reviews."""

import argparse
from datetime import datetime
import json
import re
import subprocess
import sys
import time


REPOSITORY = 'flowcool/ghostfolio-degiro-sync'
PR_FIELDS = 'headRefOid state isDraft mergeable mergeStateStatus'
PAGE = 'pageInfo { hasNextPage endCursor }'
CONNECTIONS = {
    'reviews': 'reviews(first:100, after:$cursor) { nodes { id author { login } '
        'state commit { oid } body url submittedAt } ' + PAGE + ' }',
    'threads': 'reviewThreads(first:100, after:$cursor) { nodes { id isResolved } '
        + PAGE + ' }',
    'checks': 'commits(last:1) { nodes { commit { oid statusCheckRollup { '
        'contexts(first:100, after:$cursor) { nodes { __typename '
        '... on CheckRun { id name status conclusion isRequired(pullRequestNumber:$number) } '
        '... on StatusContext { id context state creator { login } '
        'isRequired(pullRequestNumber:$number) } } ' + PAGE + ' } } } } }',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def query_for(connection=None):
    variables = '$number:Int!' + (', $cursor:String' if connection else '')
    fields = PR_FIELDS if connection is None else 'headRefOid ' + CONNECTIONS[connection]
    return ('query(' + variables + ') { repository(owner:"flowcool", '
        'name:"ghostfolio-degiro-sync") { pullRequest(number:$number) { '
        + fields + ' } } }')


def gh_query(query, number, deadline, cursor=None):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'GitHub preflight time budget exhausted')
    command = ['gh', 'api', '--hostname', 'github.com', 'graphql',
        '-f', 'query=' + query, '-F', 'number=' + str(number)]
    if cursor is not None:
        command += ['-f', 'cursor=' + cursor]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
            timeout=min(20, remaining), check=False)
        require(result.returncode == 0, 'GitHub metadata query failed')
        require(len(result.stdout) <= 8 * 1024 * 1024, 'GitHub metadata response too large')
        document = json.loads(result.stdout)
        require(isinstance(document, dict) and not document.get('errors'),
            'GitHub metadata response incomplete')
        pr = document['data']['repository']['pullRequest']
        require(isinstance(pr, dict), 'GitHub pull request unavailable')
        return pr
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError, TypeError):
        raise RuntimeError('GitHub metadata unavailable or malformed') from None


def pr_head(pr):
    head = pr.get('headRefOid')
    require(isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head),
        'Invalid pull request head metadata')
    return head


def connection_page(pr, connection, head):
    try:
        if connection == 'checks':
            commits = pr['commits']['nodes']
            require(isinstance(commits, list) and len(commits) == 1,
                'Exact-head check collection unavailable')
            commit = commits[0]['commit']
            require(commit['oid'] == head, 'Checks do not cover the selected head')
            page = commit['statusCheckRollup']['contexts']
        else:
            page = pr['reviews' if connection == 'reviews' else 'reviewThreads']
        nodes, info = page['nodes'], page['pageInfo']
        require(isinstance(nodes, list) and isinstance(info, dict)
            and type(info.get('hasNextPage')) is bool,
            'Incomplete GitHub connection metadata')
        require(all(isinstance(node, dict) and isinstance(node.get('id'), str)
            and node['id'] for node in nodes), 'Malformed GitHub connection records')
        if info['hasNextPage']:
            require(nodes and isinstance(info.get('endCursor'), str) and info['endCursor'],
                'GitHub connection pagination incomplete')
        return nodes, info
    except (KeyError, TypeError, IndexError):
        raise RuntimeError('GitHub connection unavailable or malformed') from None


def read_connection(connection, number, head, deadline):
    records, seen_ids, seen_cursors = [], set(), set()
    cursor = None
    for _ in range(10):
        pr = gh_query(query_for(connection), number, deadline, cursor)
        require(pr_head(pr) == head, 'Pull request head changed during preflight')
        nodes, info = connection_page(pr, connection, head)
        for node in nodes:
            require(node['id'] not in seen_ids, 'Repeated GitHub connection record')
            seen_ids.add(node['id'])
            records.append(node)
        if not info['hasNextPage']:
            return records
        cursor = info['endCursor']
        require(cursor not in seen_cursors, 'Repeated GitHub connection cursor')
        seen_cursors.add(cursor)
    raise RuntimeError('GitHub connection page budget exhausted')


def completed_review(reviews, head, number):
    candidates = []
    for review in reviews:
        author, commit = review.get('author'), review.get('commit')
        if (not isinstance(author, dict) or author.get('login') != 'coderabbitai'
                or not isinstance(commit, dict) or commit.get('oid') != head):
            continue
        try:
            submitted = datetime.fromisoformat(review['submittedAt'].replace('Z', '+00:00'))
            require(submitted.utcoffset() is not None, 'Invalid CodeRabbit review time')
        except (KeyError, AttributeError, ValueError, TypeError):
            raise RuntimeError('Invalid CodeRabbit review time') from None
        candidates.append((submitted, review))
    require(candidates, 'Completed CodeRabbit review of final head missing')
    newest = max(submitted for submitted, _ in candidates)
    latest = [review for submitted, review in candidates if submitted == newest]
    require(len(latest) == 1, 'Final-head CodeRabbit review evidence ambiguous')
    review = latest[0]
    require(review.get('state') in ('COMMENTED', 'APPROVED'),
        'Final-head CodeRabbit review is not completed or requests changes')
    body, url = review.get('body'), review.get('url')
    require(isinstance(body, str) and isinstance(url, str)
        and re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY)
            + '/pull/' + str(number) + r'#pullrequestreview-[0-9]+', url),
        'Invalid CodeRabbit review evidence')
    require(not re.search(r'reviews?\s+(skipped|paused|in progress)|rate[- ]limit', body, re.I),
        'Skipped, pending or rate-limited review is not evidence')
    return url


def passing_checks(checks):
    required, rabbit = 0, 0
    for check in checks:
        require(type(check.get('isRequired')) is bool, 'Required-check metadata unavailable')
        kind = check.get('__typename')
        if kind == 'CheckRun':
            name = check.get('name')
            success = check.get('status') == 'COMPLETED' and check.get('conclusion') == 'SUCCESS'
        elif kind == 'StatusContext':
            name = check.get('context')
            success = check.get('state') == 'SUCCESS'
        else:
            raise RuntimeError('Unknown GitHub check metadata')
        require(isinstance(name, str) and name, 'Malformed GitHub check name')
        if check['isRequired']:
            required += 1
            require(success, 'Required check is missing, pending or unsuccessful')
        if name == 'CodeRabbit':
            creator = check.get('creator')
            require(kind == 'StatusContext' and isinstance(creator, dict)
                and creator.get('login') == 'coderabbitai' and success,
                'CodeRabbit review status is not verified successful')
            rabbit += 1
    require(required > 0, 'Required check collection empty')
    require(rabbit == 1, 'CodeRabbit review status missing or ambiguous')
    return required


def check_merge(number):
    require(type(number) is int and 0 < number < 2 ** 31, 'Invalid pull request number')
    deadline = time.monotonic() + 90
    initial = gh_query(query_for(), number, deadline)
    head = pr_head(initial)
    require(initial.get('state') == 'OPEN' and initial.get('isDraft') is False,
        'Pull request is closed or draft')
    reviews = read_connection('reviews', number, head, deadline)
    review_url = completed_review(reviews, head, number)
    checks = passing_checks(read_connection('checks', number, head, deadline))
    threads = read_connection('threads', number, head, deadline)
    require(all(type(thread.get('isResolved')) is bool for thread in threads),
        'Review conversation metadata incomplete')
    require(all(thread['isResolved'] for thread in threads),
        'Unresolved review conversation blocks merge')
    final = gh_query(query_for(), number, deadline)
    require(pr_head(final) == head, 'Pull request head changed during preflight')
    require(final.get('state') == 'OPEN' and final.get('isDraft') is False
        and final.get('mergeable') == 'MERGEABLE' and final.get('mergeStateStatus') == 'CLEAN',
        'GitHub merge eligibility is not clean')
    return {'ready': True, 'head': head, 'review_url': review_url, 'required_checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('number', type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(check_merge(args.number), sort_keys=True))
        return 0
    except RuntimeError as error:
        print('Preflight blocked: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
