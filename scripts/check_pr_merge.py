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
DOC_PREFIXES = ('openspec/', 'docs/')
CONNECTIONS = {
    'reviews': 'reviews(first:100, after:$cursor) { nodes { id author { login __typename } '
        'state commit { oid } body url submittedAt } ' + PAGE + ' }',
    'threads': 'reviewThreads(first:100, after:$cursor) { nodes { id isResolved } '
        + PAGE + ' }',
    'files': 'files(first:100, after:$cursor) { nodes { path } ' + PAGE + ' }',
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
            page = pr['reviewThreads' if connection == 'threads' else connection]
        nodes, info = page['nodes'], page['pageInfo']
        require(isinstance(nodes, list) and isinstance(info, dict)
            and type(info.get('hasNextPage')) is bool,
            'Incomplete GitHub connection metadata')
        key = 'path' if connection == 'files' else 'id'
        require(all(isinstance(node, dict) and isinstance(node.get(key), str)
            and node[key] for node in nodes), 'Malformed GitHub connection records')
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
            key = node['path' if connection == 'files' else 'id']
            require(key not in seen_ids, 'Repeated GitHub connection record')
            seen_ids.add(key)
            records.append(node)
        if not info['hasNextPage']:
            return records
        cursor = info['endCursor']
        require(cursor not in seen_cursors, 'Repeated GitHub connection cursor')
        seen_cursors.add(cursor)
    raise RuntimeError('GitHub connection page budget exhausted')


def review_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.utcoffset() is not None, 'Invalid Pullfrog review time')
        return parsed
    except (AttributeError, ValueError, TypeError):
        raise RuntimeError('Invalid Pullfrog review time') from None


def exact_head_reviews(reviews, head):
    return [review for review in reviews
        if isinstance(review.get('author'), dict)
        and review['author'].get('login') in ('pullfrog', 'pullfrog[bot]')
        and review['author'].get('__typename') == 'Bot'
        and isinstance(review.get('commit'), dict) and review['commit'].get('oid') == head]


def completed_review(reviews, head, number):
    exact = exact_head_reviews(reviews, head)
    require(all(isinstance(r.get('body'), str) for r in exact), 'Invalid Pullfrog review body')
    # GitHub represents thread replies as empty COMMENTED reviews. They cannot
    # establish completed coverage or supersede an earlier change request.
    candidates = [r for r in exact if r.get('state') not in ('COMMENTED', 'APPROVED')
                  or r['body'].strip()]
    require(candidates, 'Completed Pullfrog review of final head missing')
    newest = max(review_time(r.get('submittedAt')) for r in candidates)
    latest = [r for r in candidates if review_time(r.get('submittedAt')) == newest]
    require(len(latest) == 1, 'Final-head Pullfrog review evidence ambiguous')
    review = latest[0]
    require(review.get('state') in ('COMMENTED', 'APPROVED'),
        'Final-head Pullfrog review is not completed or requests changes')
    body, url = review.get('body'), review.get('url')
    require(isinstance(body, str) and isinstance(url, str)
        and re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY)
            + '/pull/' + str(number) + r'#pullrequestreview-[0-9]+', url),
        'Invalid Pullfrog review evidence')
    require(not re.search(r'reviews?\s+(skipped|paused|in progress)|rate[- ]limit\s+(exceeded|reached)', body, re.I),
        'Skipped, pending or rate-limited review is not evidence')
    return url


def is_docs_only(files):
    # Same rule as pr-gate: non-empty and every path is openspec/, docs/ or *.md.
    paths = [file['path'] for file in files]
    return bool(paths) and all(path.startswith(DOC_PREFIXES) or path.endswith('.md')
        for path in paths)


def passing_checks(checks, docs_only=False):
    required = 0
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
        if name in ('CodeRabbit', 'pullfrog-approval'):
            continue
        if check['isRequired']:
            required += 1
        require(success, 'CI check is missing, pending or unsuccessful')
    require(required > 0, 'Required check collection empty')
    return required


def check_merge(number):
    require(type(number) is int and 0 < number < 2 ** 31, 'Invalid pull request number')
    deadline = time.monotonic() + 90
    initial = gh_query(query_for(), number, deadline)
    head = pr_head(initial)
    require(initial.get('state') == 'OPEN' and initial.get('isDraft') is False,
        'Pull request is closed or draft')
    docs_only = is_docs_only(read_connection('files', number, head, deadline))
    reviews, review_url = [], None
    if not docs_only:
        reviews = read_connection('reviews', number, head, deadline)
        review_url = completed_review(reviews, head, number)
    checks = passing_checks(read_connection('checks', number, head, deadline), docs_only)
    threads = read_connection('threads', number, head, deadline)
    require(all(type(thread.get('isResolved')) is bool for thread in threads),
        'Review conversation metadata incomplete')
    require(all(thread['isResolved'] for thread in threads),
        'Unresolved review conversation blocks merge')
    if not docs_only:
        refreshed = read_connection('reviews', number, head, deadline)
        require(refreshed == reviews and completed_review(refreshed, head, number) == review_url,
            'Pullfrog review evidence changed during preflight')
    final = gh_query(query_for(), number, deadline)
    require(pr_head(final) == head, 'Pull request head changed during preflight')
    require(final.get('state') == 'OPEN' and final.get('isDraft') is False
        and final.get('mergeable') == 'MERGEABLE' and final.get('mergeStateStatus') == 'CLEAN',
        'GitHub merge eligibility is not clean')
    return {'ready': True, 'head': head, 'review_url': review_url,
        'required_checks': checks, 'docs_only': docs_only}


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
