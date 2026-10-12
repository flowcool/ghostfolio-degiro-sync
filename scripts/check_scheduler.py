"""Local scheduled-process liveness; no network, credentials or journal access."""

import os
from pathlib import Path
import sys


def check_scheduler(cron, status_path='/proc/1/status'):
    if not cron.strip():
        return
    try:
        fields = dict(line.split(':', 1) for line in Path(status_path).read_text().splitlines()
                      if ':' in line)
        name = fields['Name'].strip()
        state = fields['State'].strip().split()[0]
    except (OSError, KeyError, IndexError, ValueError):
        raise RuntimeError('Scheduler process status is unavailable') from None
    if name != 'supercronic' or state not in ('R', 'S', 'D', 'I'):
        raise RuntimeError('Scheduler process is absent, stopped or not running')


def main():
    try:
        check_scheduler(os.environ.get('CRON', ''))
    except RuntimeError:
        print('Scheduler healthcheck failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
