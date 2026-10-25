#!/usr/bin/env python3
"""Explicit DEGIRO identity maintenance; never loaded by scheduled sync."""
import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_identity_maintenance as maintenance


def main(argv=None):
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
    inspect = commands.add_parser('inspect')
    rollback = commands.add_parser('rollback')
    for command in (inspect, rollback):
        for name in ('journal', 'manifest'):
            command.add_argument('--' + name, type=Path, required=True)
        command.add_argument('--manifest-sha256', required=True)
    inspect.add_argument('--snapshot', type=Path, required=True)
    inspect.add_argument('--snapshot-sha256', required=True)
    rollback.add_argument('--approval', type=Path, required=True)
    rollback.add_argument('--approval-sha256', required=True)
    rollback.add_argument('--host', required=True)
    args = parser.parse_args(argv)
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if args.command == 'preview':
            print(maintenance.preview(args.inputs, args.output))
        elif args.command == 'inspect':
            print(maintenance.yaml_bytes(maintenance.inspect(args.journal, args.manifest,
                args.manifest_sha256, args.snapshot, args.snapshot_sha256)).decode(), end='')
        elif args.command == 'rollback':
            maintenance.rollback(args.journal, args.manifest, args.manifest_sha256,
                args.approval, args.approval_sha256, args.host, None)
            print('Journal-owned comments restored; new imports retained')
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
