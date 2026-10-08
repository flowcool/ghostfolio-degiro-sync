#!/usr/bin/env python3
"""Offline exact-ID cleanup preflight. This utility has no HTTP/delete path."""
import argparse
import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, help='Private complete Ghostfolio activities JSON')
    parser.add_argument('--manifest', required=True, help='Private exact expected activities YAML')
    parser.add_argument('--output', required=True, help='New private proposed ID manifest; never overwrites')
    args = parser.parse_args(argv)
    descriptor = None
    try:
        body = json.loads(Path(args.snapshot).read_text())
        manifest = yaml.safe_load(Path(args.manifest).read_text())
        result = adapter.cleanup_preflight(body, manifest)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            descriptor = None
            yaml.safe_dump(result, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        print('Cleanup preflight only: ' + str(len(result['activity_ids'])) + ' proved IDs; zero HTTP/deletions')
        return 0
    except Exception:
        print('Cleanup preflight failed; no HTTP/deletions', file=sys.stderr)
        return 1
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == '__main__':
    sys.exit(main())
