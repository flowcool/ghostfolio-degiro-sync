#!/usr/bin/env python3
"""Explicit DEGIRO identity maintenance; never loaded by scheduled sync."""
import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_identity_maintenance as maintenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('preview')
    preview.add_argument('--inputs', type=Path, required=True)
    preview.add_argument('--output', type=Path, required=True)
    apply = commands.add_parser('apply')
    for name in ('inputs', 'manifest', 'approval', 'journal'):
        apply.add_argument('--' + name, type=Path, required=True)
    for name in ('manifest-sha256', 'approval-sha256', 'host'):
        apply.add_argument('--' + name, required=True)
    args = parser.parse_args()
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if args.command == 'preview':
            print(maintenance.preview(args.inputs, args.output))
        else:
            maintenance.apply(args.inputs, args.manifest, args.manifest_sha256,
                args.approval, args.approval_sha256, args.journal, args.host, None)
            print('Reviewed comment conversion complete; retain the journal')
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError):
        print('Identity maintenance refused; retain private evidence', file=sys.stderr)
        return 1
    finally:
        logging.disable(previous)


if __name__ == '__main__':
    raise SystemExit(main())
