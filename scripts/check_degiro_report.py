#!/usr/bin/env python3
"""Validate the plain DEGIRO reconciliation report used by candidate lab checks."""

import argparse
from pathlib import Path
import re
import sys


def check_report(text):
    lines = [re.sub(r'^.*?(?=DEGIRO reconciliation:|Finding [0-9]+:|Source identity:|Compared activity:|Expected:|Observed:|Security quantity:|Checks:|Coverage:|Reason:|Action:|End DEGIRO reconciliation|No source or destination events)', '', line)
        for line in text.splitlines()]
    reports, current, violations = 0, None, []
    in_report = False
    def finish(block):
        if block is None:
            return
        actions = [line.removeprefix('Action: ') for line in block if line.startswith('Action: ')]
        targets = [line.removeprefix('Compared activity: ') for line in block if line.startswith('Compared activity: ')]
        if len(actions) != 1 or len(targets) != 1:
            violations.append('Each finding requires one compared activity and one Action line')
            return
        status = block[0].split(': ', 1)[1]
        target, action = targets[0], actions[0]
        expected = (f'No action needed for activity {target}.' if status == 'coherent' and target != 'unavailable'
            else f'Inspect activity {target}.' if status == 'to-check' and target != 'unavailable'
            else 'Retain outside-window history; no activity selected.' if status == 'outside-window'
            else 'Inspect evidence; no activity selected.')
        if action != expected:
            violations.append('Action does not match the exact compared activity and finding')
        for prefix in ('Source identity:', 'Expected:', 'Observed:', 'Security quantity:', 'Checks:', 'Coverage:', 'Reason:'):
            if sum(line.startswith(prefix) for line in block) != 1:
                violations.append('Missing or repeated report field: ' + prefix)
        if any(re.search(r'\b[0-9]+(?:\.[0-9]+)?[eE][+-][0-9]+\b', line) for line in block):
            violations.append('Exponent notation in report')
    for line in lines:
        if line == 'DEGIRO reconciliation: nothing written':
            if in_report:
                violations.append('Nested or unfinished report')
            in_report, current = True, None
            reports += 1
        elif in_report and line.startswith('Finding '):
            finish(current)
            current = [line]
        elif in_report and line == 'End DEGIRO reconciliation':
            finish(current)
            current, in_report = None, False
        elif in_report and current is not None:
            current.append(line)
    if reports == 0 or in_report:
        violations.append('Missing complete DEGIRO report with nothing-written statement')
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log_file', nargs='?', type=Path)
    args = parser.parse_args(argv)
    text = args.log_file.read_text() if args.log_file else sys.stdin.read()
    violations = check_report(text)
    for violation in violations:
        print(violation, file=sys.stderr)
    if not violations:
        print('DEGIRO reconciliation report: PASS')
    return int(bool(violations))


if __name__ == '__main__':
    raise SystemExit(main())
