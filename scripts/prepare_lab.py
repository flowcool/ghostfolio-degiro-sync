#!/usr/bin/env python3
"""Prepare private frozen replay inputs; no HTTP, Docker or secret handling."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


def publish(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600), 'wb') as stream:
        stream.write(content)
    return hashlib.sha256(content).hexdigest()


def replay_inputs(broker, destination, mapping, quotes):
    """Check the original destination before any ID remapping or lab mutation."""
    account = destination['account']
    existing, unused = adapter.existing_activity_context(destination['activities'], account)
    config = {'source_account': broker['source_account'], 'target_account': account['id'],
        'dry_run': True, 'sync_mode': 'rolling'}
    # Pure preflight: no lock/journal or writer is needed to plan saved evidence.
    result = adapter.synchronize_locked(config, broker, account, destination['activities'],
        mapping, quotes, None, None, now=adapter.prospective_instant(broker['fetched_at']))
    seeds = [{key: row[key] for key in adapter.TRADE_FIELDS}
        for row in existing if row['accountId'] == account['id']]
    profiles = {'TEST': {'dataSource': 'YAHOO', 'symbol': 'TEST',
        'currency': 'USD', 'name': 'TEST'}}
    for row in destination['activities']['activities']:
        if row['accountId'] != account['id']:
            continue
        profile = row.get('assetProfile', row.get('SymbolProfile'))
        if profile['dataSource'] == 'YAHOO':
            symbol = profile['symbol']
            currency = profile.get('currency') or quotes.get(symbol) or row['currency']
            entry = {'dataSource': 'YAHOO', 'symbol': symbol,
                'currency': currency, 'name': symbol}
            if symbol in profiles and profiles[symbol] != entry:
                raise RuntimeError('Conflicting captured lab asset profiles')
            profiles[symbol] = entry
    for symbol, currency in quotes.items():
        profiles.setdefault(symbol, {'dataSource': 'YAHOO', 'symbol': symbol,
            'currency': currency, 'name': symbol})
    return seeds, profiles, result


def prepare(args):
    root = Path(args.output_directory).resolve()
    paths = {name: Path(getattr(args, name)).resolve() for name in
        ('broker', 'destination', 'mapping')}
    if any(root == path or root in path.parents for path in paths.values()):
        raise RuntimeError('Lab output aliases retained inputs')
    raw = {name: adapter.read_private_evidence(getattr(args, name),
        getattr(args, name + '_sha256')) for name in paths}
    broker, destination = (json.loads(raw[name], object_pairs_hook=adapter.unique_evidence_pairs)
        for name in ('broker', 'destination'))
    mapping, quotes = adapter.verified_mapping_document(yaml.safe_load(raw['mapping']))
    seeds, profiles, planned = replay_inputs(broker, destination, mapping, quotes)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest = {'version': 1, 'inputs': {}, 'expected_proposals': planned['proposed'],
        'expected_cash': planned['cash'], 'seed_count': len(seeds)}
    for name in paths:
        filename = name + ('.yaml' if name == 'mapping' else '.json')
        manifest['inputs'][name] = {'path': filename, 'sha256': publish(root / filename, raw[name])}
    manifest['profiles_sha256'] = publish(root / 'profiles.json',
        json.dumps(profiles, sort_keys=True, allow_nan=False).encode())
    digest = publish(root / 'manifest.yaml', yaml.safe_dump(manifest).encode())
    print('Prepared private lab replay; manifest SHA256 ' + digest)
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('broker', 'destination', 'mapping'):
        parser.add_argument('--' + name, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--output-directory', required=True)
    try:
        prepare(parser.parse_args())
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        print('Lab preparation refused; private details suppressed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
