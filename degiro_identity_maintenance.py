"""Adapted from IBKR v3.0.0 (403b4ccf), identity_maintenance.py.

Offline evidence and private-output primitives for identity maintenance.

No configuration loader, credential reader or HTTP client belongs here.
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def safe_path(path):
    require(not any((part.is_symlink() for part in (path, *path.parents))), 'Symlink paths are not allowed')
    return path.resolve()

def read_evidence(path, expected_hash):
    data = safe_path(path).read_bytes()
    require(digest(data) == expected_hash, 'Evidence hash changed')
    return data

def exact_json(data):

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise RuntimeError('Non-finite JSON number')
    return json.loads(data, parse_float=Decimal, parse_int=int, parse_constant=invalid_constant, object_pairs_hook=pairs)

def canonical_json(value):
    """Keep exact decimal evidence as strings; runtime payloads retain numbers."""

    def default(item):
        if isinstance(item, Decimal) and item.is_finite():
            return str(item)
        raise TypeError('Unsupported manifest value')
    return (json.dumps(value, default=default, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()

def instant(value):
    require(isinstance(value, str), 'Missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Timestamp needs an explicit timezone')
    return parsed

def publish_private(output, files, inputs):
    """Exclusive publication cannot replace an input or an earlier review."""
    target = safe_path(output)
    for path in inputs:
        source = safe_path(path)
        require(not source.is_relative_to(target) and (not target.is_relative_to(source)), 'Output overlaps evidence')
    for name in files:
        require(Path(name).name == name, 'Invalid output name')
    require(not target.exists(), 'Output already exists')
    with tempfile.TemporaryDirectory(prefix='.identity-preview-', dir=target.parent) as staging:
        stage = Path(staging) / 'review'
        stage.mkdir(mode=448)
        for name, data in files.items():
            descriptor = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 384)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        target.mkdir(mode=448, parents=False, exist_ok=False)
        try:
            stage.rename(target)
        except OSError:
            target.rmdir()
            raise

import re
import yaml
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from zoneinfo import ZoneInfo

def keyed_yaml(data, *, allow_float=False):
    """Accept JSON-compatible keyed YAML without duplicate keys or aliases."""
    root = yaml.compose(data, Loader=yaml.SafeLoader)
    seen = set()

    def check(node):
        require(id(node) not in seen, 'YAML aliases are not allowed')
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys = set()
            for key, value in node.value:
                require(isinstance(key, yaml.ScalarNode) and key.tag == 'tag:yaml.org,2002:str' and key.value and (key.value not in keys), 'Invalid or duplicate YAML key')
                keys.add(key.value)
                check(value)
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                check(child)
        else:
            require(isinstance(node, yaml.ScalarNode) and node.tag in {'tag:yaml.org,2002:str', 'tag:yaml.org,2002:int', 'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:null', *({'tag:yaml.org,2002:float'} if allow_float else set())}, 'Unsupported YAML value')
    check(root)
    result = yaml.safe_load(data)
    require(isinstance(result, dict), 'Inputs must be keyed YAML')
    return result

def text(value):
    return isinstance(value, str) and bool(value.strip())

def validate_snapshot(snapshot, metadata):
    require(isinstance(metadata, dict), 'Missing snapshot metadata')
    require(metadata.get('complete') is True and metadata.get('unredacted') is True, 'Incomplete or redacted snapshot')
    for key in ('capture_ref', 'destination_version', 'destination_image'):
        require(text(metadata.get(key)), 'Missing snapshot provenance')
    require(re.fullmatch('sha256:[0-9a-f]{64}', metadata['destination_image']), 'Invalid destination image digest')
    instant(metadata.get('captured_at'))
    require(isinstance(snapshot, dict) and isinstance(snapshot.get('activities'), list), 'Invalid snapshot')
    rows = snapshot['activities']
    require(type(metadata.get('count')) is int and metadata['count'] == len(rows) and type(snapshot.get('count')) is int and (snapshot['count'] == len(rows)), 'Incomplete snapshot count')
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and text(row.get('id')) and (row['id'] not in ids), 'Missing or duplicate activity ID')
        ids.add(row['id'])
        require('comment' in row and (row['comment'] is None or isinstance(row['comment'], str)), 'Missing or redacted comment')
        for key in ('quantity', 'unitPrice', 'fee'):
            require(type(row.get(key)) is int or isinstance(row.get(key), Decimal) and row[key].is_finite(), 'Missing or redacted financial number')
        require(text(row.get('type')) and type(row.get('isDraft')) is bool and isinstance(row.get('tags'), list), 'Incomplete activity context')
        for key in ('accountId', 'currency'):
            require(key in row and (row[key] is None or text(row[key])), 'Missing activity context')
        instant(row.get('date'))
        require(any((key in row for key in ('assetProfile', 'SymbolProfile'))), 'Missing security context')
        for key in ('assetProfile', 'SymbolProfile'):
            if key in row:
                require(row[key] is None or isinstance(row[key], dict), 'Invalid security context')


def yaml_bytes(value):
    # JSON-compatible exact records use decimal strings in evidence only.
    def plain(item):
        if isinstance(item, float):
            require(__import__('math').isfinite(item), 'Non-finite evidence')
            return str(item)
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return item
    return yaml.safe_dump(plain(json.loads(canonical_json(value))), sort_keys=True).encode()


def implementation_hashes():
    root = Path(__file__).resolve().parent
    paths = ['degiro_identity_maintenance.py', 'scripts/migrate_degiro_identity.py',
             'ghostfolio_core.py', *[str(p.relative_to(root)) for p in
                sorted((root / 'ghostfolio_degiro_sync').glob('*.py'))],
             'ghostfolio_degiro_sync/cash-rules.yaml']
    return {name: digest((root / name).read_bytes()) for name in paths}


def replay_selection(reports, rows, config, mapping):
    from ghostfolio_degiro_sync import sync
    results = {}
    for name in config['replay_order']:
        ref, snapshot = reports[name]
        account = ref['source_account']
        target = config['accounts'][account]
        try:
            result = sync.select_account_activities(
                {'source_account': account, 'target_account': target['id'],
                 'dry_run': True, 'sync_mode': 'full_history'},
                snapshot, target, {'count': len(rows), 'activities': rows},
                mapping['symbols'], mapping['quote_currencies'], now=instant(config['clock']))
            results[name] = {'outcome': 'selected', 'result': asdict(result)}
        except (RuntimeError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            results[name] = {'outcome': 'refused', 'reason': str(error), 'error': type(error).__name__}
    return results


def migration_evidence(inputs):
    from ghostfolio_degiro_sync import diagnostics, ghostfolio, identity
    config_path = safe_path(inputs)
    config_bytes = config_path.read_bytes()
    config = keyed_yaml(config_bytes)
    require(config.get('schema') == 'degiro-migration-inputs-v1', 'Unsupported inputs schema')
    require(re.fullmatch(r'[0-9a-f]{40}', str(config.get('tool_commit', ''))), 'Missing tool commit')
    instant(config.get('clock'))
    accounts = config.get('accounts')
    require(config.get('inventory_complete') is True and isinstance(accounts, dict) and accounts,
            'Missing complete configured source inventory')
    for source, target in accounts.items():
        identity.broker_identity(source)
        require(isinstance(target, dict) and text(target.get('id')), 'Missing account mapping')
    captured = {config_path: config_bytes}
    def read(ref):
        require(isinstance(ref, dict) and text(ref.get('path')), 'Missing evidence reference')
        path = safe_path(config_path.parent / ref['path'])
        require(path not in captured, 'Duplicate evidence path')
        data = read_evidence(path, ref.get('sha256'))
        captured[path] = data
        return data
    mapping = keyed_yaml(read(config.get('mapping')))
    require(isinstance(mapping.get('symbols'), dict) and isinstance(mapping.get('quote_currencies'), dict),
            'Missing mapping and quote currencies')
    metadata = config.get('snapshot')
    snapshot = exact_json(read(metadata))
    validate_snapshot(snapshot, metadata)
    rows = snapshot['activities']
    refs = config.get('reports')
    require(isinstance(refs, dict) and refs, 'Missing keyed source reports')
    order = config.get('replay_order')
    require(isinstance(order, list) and len(order) == len(refs) and set(order) == set(refs),
            'Replay order must contain every report once')
    reports, events, windows = {}, {}, {}
    for name, ref in sorted(refs.items()):
        account = ref.get('source_account')
        require(account in accounts, 'Source report outside inventory')
        # Runtime source IDs remain integers. JSON fractional tokens retain Decimal.
        source = exact_json(read(ref))
        require(str(source.get('source_account')) == account, 'Source account mismatch')
        low, high = source.get('from_date'), source.get('to_date')
        from datetime import date
        require(isinstance(low, str) and isinstance(high, str)
                and date.fromisoformat(low) <= date.fromisoformat(high), 'Missing source window')
        reports[name] = ref, source
        windows[name] = {'source_account': account, 'from_date': low, 'to_date': high,
                         'sha256': ref['sha256'], 'complete_history': False}
        activities = diagnostics.exact_source_activities(source, accounts[account]['id'],
                          mapping['symbols'], mapping['quote_currencies'])
        for activity in activities or []:
            key = identity.canonical_comment(activity['comment'], activity['type'])
            item = events.setdefault(key, {'variants': {}, 'reports': []})
            item['variants'][digest(canonical_json(activity))] = activity
            item['reports'].append(name)
    require({ref['source_account'] for ref in refs.values()} == accounts.keys(),
            'Inventory accounts lack saved reports')
    owners = {}
    for row in rows:
        try:
            key = identity.canonical_comment(row['comment'], row['type'])
        except RuntimeError:
            key = None
        if key:
            owners.setdefault(key, []).append(row['id'])
    decisions, replacements = {}, {}
    for row in sorted(rows, key=lambda item: item['id']):
        comment = row['comment']
        decision = {'old_comment': comment, 'new_comment': None,
                    'fingerprint': digest(canonical_json(row)), 'source_refs': []}
        status, reason = 'manual/other broker', 'No DEGIRO ownership claim'
        try:
            owner = identity.parse_identity(comment, row['type'])
        except RuntimeError:
            owner = None
            status, reason = 'unsupported', 'Malformed reserved identity'
        if owner:
            key = identity.canonical_comment(comment)
            event = events.get(key)
            decision['new_comment'] = identity.versioned_comment(*owner)
            decision['source_refs'] = sorted(set(event['reports'])) if event else []
            if len(owners[key]) != 1:
                status, reason = 'ambiguous', 'Duplicate legacy/versioned ownership'
            elif comment.startswith('DEGIRO#v1#'):
                status, reason = 'already versioned', 'No conversion needed'
            elif owner[0] not in accounts or accounts[owner[0]]['id'] != row['accountId']:
                status, reason = 'conflicting', 'Source account was remapped or is undeclared'
            elif not ghostfolio.core.activity_is_active(row):
                status, reason = 'unsupported', 'Inactive historical activity remains intact'
            elif not event:
                status, reason = 'unproven', 'No exact saved source association; history coverage missing'
            elif len(event['variants']) != 1:
                status, reason = 'ambiguous', 'Conflicting saved source events'
            else:
                expected = next(iter(event['variants'].values()))
                profile = row.get('assetProfile') or row.get('SymbolProfile') or {}
                normalized = {**row, 'symbol': profile.get('symbol'), 'dataSource': profile.get('dataSource')}
                # MANUAL UUID must be proven through exact submitted source identity and money.
                try:
                    accepted, _ = ghostfolio.prove_accepted_subset([{**expected, 'comment': comment}], [normalized])
                    exact = len(accepted) == 1
                except RuntimeError:
                    exact = False
                window_ok = any(windows[name]['from_date'] <= instant(row['date']).astimezone(ZoneInfo('Europe/Zurich')).date().isoformat() <= windows[name]['to_date']
                                for name in event['reports'])
                if exact and window_ok:
                    status, reason = 'eligible', 'Unique exact source and stored ownership'
                    after = {**row, 'comment': decision['new_comment']}
                    replacements[row['id']] = {'old_comment': comment, 'new_comment': decision['new_comment'],
                        'before_fingerprint': decision['fingerprint'],
                        'after_fingerprint': digest(canonical_json(after))}
                else:
                    status, reason = 'conflicting', 'Source financial context or window differs'
        decision.update(status=status, reason=reason)
        decisions[row['id']] = decision
    changed = [{**row, 'comment': replacements.get(row['id'], {}).get('new_comment', row['comment'])}
               for row in rows]
    before = replay_selection(reports, rows, config, mapping)
    after = replay_selection(reports, changed, config, mapping)
    equal = canonical_json(before) == canonical_json(after) and all(
        value['outcome'] == 'selected' for value in before.values())
    if not equal:
        for row_id in replacements:
            decisions[row_id].update(status='unproven', reason='Complete selection proof unavailable or changed')
        replacements = {}
    manifest = {'schema': 'degiro-migration-preview-v1', 'actionable': False,
        'tool_commit': config['tool_commit'], 'implementation': implementation_hashes(),
        'bindings': {'inputs': digest(config_bytes), 'mapping': config['mapping']['sha256'],
                     'snapshot': metadata['sha256']}, 'scope': accounts,
        'snapshot': {k: v for k, v in metadata.items() if k != 'path'}, 'windows': windows,
        'rows': decisions, 'replacements': replacements,
        'counts': dict(sorted(Counter(item['status'] for item in decisions.values()).items())),
        'selection_proof': {'equal': equal, 'clock': config['clock'], 'before': before, 'after': after},
        'gates': {key: {'status': 'pending', 'source_refs': []} for key in
            ('source_lifetime_identity', 'target_dto', 'manual_zero_uuid', 'background_effects', 'pacing', 'reversal')},
        'limitations': ['Saved source windows do not prove lifetime history completeness.',
                        'Preview never authorizes financial writes or an old binary restart.']}
    for path, data in captured.items():
        require(path.read_bytes() == data, 'Input changed during preview')
    return manifest, captured


def preview(inputs, output):
    manifest, captured = migration_evidence(Path(inputs))
    data = yaml_bytes(manifest)
    manifest_hash = digest(data)
    publish_private(Path(output), {'manifest.yaml': data, 'manifest.sha256': (manifest_hash + '\n').encode()}, list(captured))
    return manifest_hash
