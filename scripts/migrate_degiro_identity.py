#!/usr/bin/env python3
"""Explicit DEGIRO identity maintenance; never loaded by scheduled sync."""
import argparse
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
    args = parser.parse_args()
    try:
        print(maintenance.preview(args.inputs, args.output))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        print('Identity maintenance refused; retain private evidence', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
