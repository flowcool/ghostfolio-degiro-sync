#!/usr/bin/env python3
"""GET-only positive import recovery; explicit local confirmation, no replay."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-intent-id', required=True, help='Exact pending request selected before recovery')
    parser.add_argument('--confirm-local-state', action='store_true',
        help='Confirm only the matched private import intent; no financial mutation')
    args = parser.parse_args(argv)
    config = {'ghost_host': os.environ.get('GHOST_HOST'), 'ghost_token': os.environ.get('GHOST_TOKEN'),
        'target_account': os.environ.get('GHOST_ACCOUNT_ID'),
        'source_account': os.environ.get('DEGIRO_ACCOUNT_ID'), 'state_dir': os.environ.get('STATE_DIR')}
    try:
        result = adapter.readback_import_intent(config, expected_intent_id=args.expected_intent_id,
            confirm=args.confirm_local_state)
        action = 'confirmed locally' if result['confirmed'] else 'verified; intent retained'
        print('Positive import recovery: ' + str(result['matched']) + ' exact activities ' + action
              + '; GET only, no replay or financial mutation'
              + '; snapshot SHA-256=' + result['snapshot_sha256'])
        return 0
    except Exception:
        print('Positive import recovery failed; inspect private state, no financial mutation', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
