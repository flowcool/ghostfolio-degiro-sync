"""Merge only after successful live preflight, pinning the reviewed head."""

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import quote

if __package__:
    from .check_pr_merge import REPOSITORY, check_merge, require
else:
    from check_pr_merge import REPOSITORY, check_merge, require


METHODS = ('merge', 'squash', 'rebase')


def policy_metadata(endpoint):
    try:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
            '--method', 'GET', endpoint], capture_output=True, text=True,
            timeout=20, check=False)
        require(result.returncode == 0, 'Merge policy query failed')
        require(len(result.stdout) <= 8 * 1024 * 1024, 'Merge policy response too large')
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError):
        raise RuntimeError('Merge policy unavailable or malformed') from None


def check_merge_method(number, method, head):
    require(type(number) is int and 0 < number < 2 ** 31, 'Invalid pull request number')
    require(isinstance(method, str) and method in METHODS, 'Invalid merge method')
    require(isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head),
        'Invalid proven head')
    repository = policy_metadata('repos/' + REPOSITORY)
    fields = {'merge': 'allow_merge_commit', 'squash': 'allow_squash_merge',
        'rebase': 'allow_rebase_merge'}
    require(isinstance(repository, dict)
        and all(type(repository.get(field)) is bool for field in fields.values()),
        'Repository merge policy incomplete')
    allowed = {name for name, field in fields.items() if repository[field]}
    pull = policy_metadata('repos/' + REPOSITORY + '/pulls/' + str(number))
    try:
        base = pull['base']['ref']
        require(pull['base']['repo']['full_name'] == REPOSITORY
            and pull['head']['sha'] == head, 'Pull request changed during policy lookup')
        require(pull['state'] == 'open' and pull['draft'] is False,
            'Pull request is closed or draft')
        require(isinstance(base, str) and base, 'Base branch unavailable')
    except (KeyError, TypeError):
        raise RuntimeError('Pull request policy metadata incomplete') from None
    rules = policy_metadata('repos/' + REPOSITORY + '/rules/branches/' + quote(base, safe=''))
    require(isinstance(rules, list), 'Effective branch policy incomplete')
    for rule in rules:
        require(isinstance(rule, dict) and isinstance(rule.get('type'), str),
            'Effective branch rule malformed')
        if rule['type'] == 'pull_request':
            params = rule.get('parameters')
            methods = params.get('allowed_merge_methods') if isinstance(params, dict) else None
            require(isinstance(methods, list) and methods
                and all(isinstance(name, str) and name in METHODS for name in methods),
                'Effective branch merge methods incomplete')
            allowed.intersection_update(methods)
        elif rule['type'] == 'required_linear_history':
            allowed.discard('merge')
    require(method in allowed, 'Merge method ' + method + ' is disabled for base branch ' + base)
    return base


def merge_pr(number, method='merge'):
    require(type(number) is int and 0 < number < 2 ** 31, 'Invalid pull request number')
    require(isinstance(method, str) and method in METHODS, 'Invalid merge method')
    proof = check_merge(number)
    require(isinstance(proof, dict) and proof.get('ready') is True,
        'Merge preflight did not return readiness')
    head, url, checks = proof.get('head'), proof.get('review_url'), proof.get('required_checks')
    docs_only = proof.get('docs_only') is True
    require(isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head)
        and type(checks) is int and checks > 0 and (url is None if docs_only else isinstance(url, str)
        and re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY)
            + '/pull/' + str(number) + r'#(?:pullrequestreview|issuecomment)-[0-9]+', url)),
        'Merge preflight returned malformed evidence')
    base = check_merge_method(number, method, head)
    # No shell, auto-merge, admin bypass, stored proof or caller-selected SHA.
    try:
        result = subprocess.run(['gh', 'pr', 'merge', str(number), '--repo', 'github.com/' + REPOSITORY,
            '--' + method, '--match-head-commit', head], capture_output=True, text=True,
            timeout=120, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise RuntimeError('Merge outcome unavailable; inspect GitHub before retrying') from None
    require(result.returncode == 0, 'Merge command failed; inspect GitHub before retrying')
    return dict(proof, method=method, base=base, merge_command_succeeded=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('number', type=int)
    parser.add_argument('--method', choices=METHODS, default='merge')
    args = parser.parse_args()
    try:
        print(json.dumps(merge_pr(args.number, args.method), sort_keys=True))
        return 0
    except RuntimeError as error:
        print('Merge blocked: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
