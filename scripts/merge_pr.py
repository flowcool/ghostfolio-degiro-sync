"""Merge only after successful live preflight, pinning the reviewed head."""

import argparse
import json
import re
import subprocess
import sys

if __package__:
    from .check_pr_merge import REPOSITORY, check_merge, require
else:
    from check_pr_merge import REPOSITORY, check_merge, require


def merge_pr(number):
    require(type(number) is int and 0 < number < 2 ** 31, 'Invalid pull request number')
    proof = check_merge(number)
    require(isinstance(proof, dict) and proof.get('ready') is True,
        'Merge preflight did not return readiness')
    head, url, checks = proof.get('head'), proof.get('review_url'), proof.get('required_checks')
    require(isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head)
        and type(checks) is int and checks > 0 and isinstance(url, str)
        and re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY)
            + '/pull/' + str(number) + r'#(?:pullrequestreview|issuecomment)-[0-9]+', url),
        'Merge preflight returned malformed evidence')
    # No shell, auto-merge, admin bypass, stored proof or caller-selected SHA.
    try:
        result = subprocess.run(['gh', 'pr', 'merge', str(number), '--repo', REPOSITORY,
            '--merge', '--match-head-commit', head], capture_output=True, text=True,
            timeout=120, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise RuntimeError('Merge outcome unavailable; inspect GitHub before retrying') from None
    require(result.returncode == 0, 'Merge command failed; inspect GitHub before retrying')
    return dict(proof, merge_command_succeeded=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('number', type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(merge_pr(args.number), sort_keys=True))
        return 0
    except RuntimeError as error:
        print('Merge blocked: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
