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
        require(text(row.get('type')) and ('isDraft' not in row or type(row['isDraft']) is bool)
                and isinstance(row.get('tags'), list), 'Incomplete activity context')
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


MINIMUM_DESTINATION_VERSION = (3, 86, 0)


def supported_destination_version(version):
    """Compare semantic versions with a floor, without pinning a target release."""
    if not isinstance(version, str):
        return False
    matched = re.fullmatch(
        r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
        r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
        r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?', version)
    if matched is None:
        return False
    prerelease = matched[4]
    if prerelease and any(part.isdecimal() and len(part) > 1 and part[0] == '0'
                          for part in prerelease.split('.')):
        return False
    release = tuple(int(part) for part in matched.group(1, 2, 3))
    return release > MINIMUM_DESTINATION_VERSION or (
        release == MINIMUM_DESTINATION_VERSION and prerelease is None)


def update_class(row):
    profile = row.get('assetProfile') or row.get('SymbolProfile') or {}
    return f"{row['type']}:{profile.get('dataSource')}"


def numeric_json(value):
    """Encode exact JSON numeric tokens; never serialize Decimal as a string."""
    if value is None or isinstance(value, (str, bool)):
        return json.dumps(value, ensure_ascii=True).encode()
    if type(value) is int:
        return str(value).encode()
    if isinstance(value, Decimal):
        require(value.is_finite(), 'Non-finite request number')
        return format(value, 'f').encode()
    if isinstance(value, list):
        return b'[' + b','.join(numeric_json(item) for item in value) + b']'
    if isinstance(value, dict):
        require(all(isinstance(key, str) for key in value), 'Invalid JSON key')
        return b'{' + b','.join(numeric_json(key) + b':' + numeric_json(item)
                               for key, item in sorted(value.items())) + b'}'
    raise RuntimeError('Unqualified numeric transport')


def comment_payload(row, comment):
    """Explicit Ghostfolio UpdateOrderDto allowlist, never a GET object echo."""
    from math import isfinite
    from ghostfolio_degiro_sync import identity
    identity.parse_identity(comment, row['type'])
    profile = row.get('assetProfile') or row.get('SymbolProfile')
    require(isinstance(profile, dict) and profile.get('dataSource') in ('YAHOO', 'MANUAL')
            and text(profile.get('symbol')) and profile['symbol'] == profile['symbol'].strip(),
            'Unsupported update profile')
    from ghostfolio_degiro_sync import ghostfolio
    require(row['type'] in ('BUY', 'SELL', 'DIVIDEND', 'FEE', 'INTEREST')
            and ghostfolio.core.activity_is_active(row) and ghostfolio.core.activity_date_is_current(row)
            and text(row.get('accountId'))
            and text(row.get('currency')), 'Unsupported activity context')
    payload = {key: row[key] for key in ('id', 'accountId', 'currency', 'date', 'type')}
    payload.update(comment=comment, symbol=profile['symbol'], dataSource=profile['dataSource'])
    for field in ('quantity', 'unitPrice', 'fee'):
        value = row[field]
        require(type(value) is int or isinstance(value, Decimal), 'Unqualified numeric evidence')
        require(value >= 0 and isfinite(float(value)) and Decimal(str(float(value))) == value,
                'Update number cannot be preserved by target numeric transport')
        payload[field] = value
    tags = row['tags']
    require(all(isinstance(tag, dict) and text(tag.get('id')) for tag in tags), 'Unproven tag identity')
    payload['tags'] = [tag['id'] for tag in tags]
    require(len(set(payload['tags'])) == len(tags), 'Duplicate update tags')
    numeric_json(payload)
    return payload


def maintenance_request(method, host, token, row_id=None, payload=None):
    """Dedicated exact-origin allowlist. No import, cash, delete or retries."""
    import requests
    from urllib.parse import quote, urlsplit
    from ghostfolio_degiro_sync import config, diagnostics, ghostfolio
    import ghostfolio_core as core
    config.validate_ghost_host(host)
    require(isinstance(token, str) and bool(re.fullmatch(r'[!-~]+', token)), 'Invalid maintenance token')
    require(method == 'GET' and row_id is None and payload is None or
            method == 'PUT' and text(row_id) and isinstance(payload, dict) and payload.get('id') == row_id,
            'Request outside maintenance boundary')
    path = '/api/v1/activities' + ('/' + quote(row_id, safe='') if row_id is not None else '')
    ghostfolio.warn_ghost_http(host)
    with diagnostics.private_broker_logs(), requests.Session() as session:
        session.trust_env = False
        headers = core.ghost_headers(token)
        headers['Content-Type'] = 'application/json'
        request = requests.Request(method, host + path, headers=headers,
            data=numeric_json(payload) if payload is not None else None)
        prepared = session.prepare_request(request)
        parts = urlsplit(prepared.url)
        require(f'{parts.scheme}://{parts.netloc}' == host and parts.path == path
                and not parts.query and not parts.fragment, 'Maintenance target changed')
        try:
            response = session.send(prepared, timeout=(10, 60), allow_redirects=False, verify=True, stream=False)
        except requests.RequestException:
            raise RuntimeError('Maintenance request unresolved; retain pending journal') from None
        require(200 <= response.status_code < 300, 'Maintenance HTTP outcome unresolved')
        return exact_json(response.content) if method == 'GET' else None


def qualified_approval(permit, reviewed, manifest_sha256, host, rows, direction):
    from ghostfolio_degiro_sync import config
    config.validate_ghost_host(host)
    require(permit.get('schema') == 'degiro-migration-approval-v1'
            and permit.get('authorization') == direction + '-reviewed-comments', 'Invalid operation authorization')
    require(permit.get('host') == host and permit.get('manifest_sha256') == manifest_sha256,
            'Approval target or manifest changed')
    for key in ('operation_plan_ref', 'backup_ref', 'writer_exclusion_ref', 'settlement_ref', 'owner_id', 'state_dir'):
        require(text(permit.get(key)), 'Missing qualified operation prerequisite')
    require(permit.get('writers_stopped') is True and permit.get('requests_settled') is True,
            'Competing writers or requests remain')
    require(supported_destination_version(reviewed['snapshot']['destination_version']),
            'Ghostfolio version must be semantic and at least 3.86.0')
    for key in ('destination_version', 'destination_image'):
        require(permit.get(key) == reviewed['snapshot'][key], 'Destination image or version changed')
    require(type(permit.get('write_count')) is int and permit['write_count'] == len(rows), 'Unapproved write count')
    batch, pause = permit.get('batch_size'), Decimal(str(permit.get('pause_seconds')))
    require(type(batch) is int and batch > 0 and pause.is_finite() and pause >= 0
            and __import__('math').isfinite(float(pause)), 'Missing qualified pacing')
    for row in rows:
        require(row.get('userId') == permit['owner_id'], 'Unproven migration owner')
        qualification = permit.get('qualifications', {}).get(update_class(row), {})
        for key in ('source_identity', 'target_dto', 'manual_zero_uuid', 'background_effects', 'pacing', 'reversal'):
            gate = qualification.get(key, {})
            require(gate.get('status') == 'pass' and isinstance(gate.get('source_refs'), list)
                    and gate['source_refs'] and all(text(ref) for ref in gate['source_refs']),
                    'Missing exact-image class qualification')
    return batch, float(pause)


def journal_lock(path, evidence):
    """Private journal lock; callers also hold the normal destination account locks."""
    import fcntl
    import stat
    from ghostfolio_degiro_sync.journal import private_state_file
    path = safe_path(Path(path))
    info = path.parent.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            'Unsafe journal directory')
    lock_path = safe_path(Path(str(path) + '.lock'))
    for target in (path, lock_path):
        for source in evidence:
            require(not source.is_relative_to(target) and not target.is_relative_to(source)
                    and (not target.exists() or not target.samefile(source)), 'Journal overlaps evidence')
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_state_file(descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def persist(path, record):
    from ghostfolio_degiro_sync.journal import write_journal
    # Reuse atomic fsync + directory fsync. Exact decimals are evidence strings.
    document = keyed_yaml(yaml_bytes(record))
    write_journal({'directory': path.parent, 'path': path, 'document': document})


def owned_readback(expected, observed):
    """Only an owned PUT can advance its backend-managed Order timestamp."""
    require(isinstance(observed, dict), 'Missing owned activity readback')
    comparable = observed
    if 'updatedAt' in expected:
        require(instant(observed.get('updatedAt')) >= instant(expected['updatedAt']),
                'Owned activity timestamp regressed')
        comparable = {**observed, 'updatedAt': expected['updatedAt']}
    require(canonical_json(comparable) == canonical_json(expected), 'Owned activity context changed')
    return observed


def apply(inputs, manifest, manifest_sha256, approval, approval_sha256, journal, host, token):
    from contextlib import ExitStack
    import time
    from ghostfolio_degiro_sync.journal import account_journal
    proposed, captured = migration_evidence(Path(inputs))
    reviewed_bytes = read_evidence(Path(manifest), manifest_sha256)
    require(reviewed_bytes == yaml_bytes(proposed), 'Reviewed manifest changed')
    reviewed = keyed_yaml(reviewed_bytes)
    require(reviewed['selection_proof']['equal'] and reviewed['replacements'], 'No proven replacements')
    permit_bytes = read_evidence(Path(approval), approval_sha256)
    permit = keyed_yaml(permit_bytes)
    config = keyed_yaml(captured[safe_path(Path(inputs))])
    snapshot_path = safe_path(Path(inputs).parent / config['snapshot']['path'])
    expected = {row['id']: row for row in exact_json(captured[snapshot_path])['activities']}
    selected = [expected[row_id] for row_id in reviewed['replacements']]
    batch, pause = qualified_approval(permit, reviewed, manifest_sha256, host, selected, 'apply')
    payloads = {row['id']: comment_payload(row, reviewed['replacements'][row['id']]['new_comment']) for row in selected}
    captured.update({safe_path(Path(manifest)): reviewed_bytes, safe_path(Path(approval)): permit_bytes})
    path = safe_path(Path(journal))
    descriptor = journal_lock(path, captured)
    try:
        require(not path.exists(), 'Existing migration journal; automatic retry refused')
        with ExitStack() as stack:
            for source, target in sorted(config['accounts'].items()):
                state = stack.enter_context(account_journal({'state_dir': permit['state_dir'],
                    'ghost_host': host, 'source_account': source, 'target_account': target['id']}))
                require(state['document']['pending'] is None, 'Unsettled normal synchronization intent')
            records = {row['id']: {**reviewed['replacements'][row['id']], 'preimage': row,
                'request_payload': payloads[row['id']],
                'request_body_sha256': digest(numeric_json(payloads[row['id']])), 'status': 'prepared'} for row in selected}
            record = {'schema': 'degiro-migration-journal-v1', 'host': host,
                'manifest_sha256': manifest_sha256, 'approval_sha256': approval_sha256,
                'scope': reviewed['scope'], 'state_dir': permit['state_dir'], 'status': 'prepared', 'rows': records}
            file = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(file)
            persist(path, record)
            def check(written=None):
                fresh = maintenance_request('GET', host, token)
                validate_snapshot(fresh, reviewed['snapshot'])
                actual = {row['id']: row for row in fresh['activities']}
                if written is not None:
                    expected[written] = owned_readback(expected[written], actual.get(written))
                require(actual.keys() == expected.keys() and all(canonical_json(actual[k]) == canonical_json(v)
                    for k, v in expected.items()), 'Destination context, protected rows or occupancy changed')
                for source, data in captured.items():
                    require(source.read_bytes() == data, 'Reviewed evidence changed')
                require(implementation_hashes() == reviewed['implementation'], 'Implementation changed')
            token = maintenance_token(host, token)
            check()
            for index, row_id in enumerate(reviewed['replacements']):
                if index and index % batch == 0:
                    time.sleep(pause)
                check()
                records[row_id]['status'] = 'pending'
                record['status'] = 'in_progress'
                persist(path, record)
                maintenance_request('PUT', host, token, row_id, payloads[row_id])
                expected[row_id] = {**expected[row_id], 'comment': reviewed['replacements'][row_id]['new_comment']}
                check(row_id)
                records[row_id]['postimage'] = expected[row_id]
                records[row_id]['status'] = 'verified'
                persist(path, record)
            record['status'] = 'complete'
            persist(path, record)
    finally:
        os.close(descriptor)


def maintenance_token(host, token):
    if token is not None:
        return token
    from ghostfolio_degiro_sync import config, ghostfolio
    credentials = config.load_ghost_credentials()
    require(credentials['ghost_host'] == host, 'Credential origin differs from approved target')
    ghostfolio.authenticate_ghostfolio(credentials)
    return credentials['ghost_token']


def migration_journal(journal, manifest, manifest_sha256):
    from ghostfolio_degiro_sync.journal import private_state_file
    reviewed = keyed_yaml(read_evidence(Path(manifest), manifest_sha256))
    descriptor = os.open(safe_path(Path(journal)), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        private_state_file(stream.fileno())
        data = stream.read(1_000_001)
    require(len(data) <= 1_000_000, 'Journal exceeds state budget')
    record = keyed_yaml(data)
    require(record.get('schema') == 'degiro-migration-journal-v1'
            and record.get('manifest_sha256') == manifest_sha256
            and record.get('scope') == reviewed['scope'], 'Journal binding changed')
    require(isinstance(record.get('rows'), dict) and record['rows'].keys() == reviewed['replacements'].keys(),
            'Journal ownership changed')
    for row_id, entry in record['rows'].items():
        replacement = reviewed['replacements'][row_id]
        require(all(entry.get(key) == value for key, value in replacement.items()), 'Journal replacement changed')
        before = entry['preimage']
        require(before.get('id') == row_id and before.get('comment') == entry['old_comment']
                and digest(canonical_json(before)) == entry['before_fingerprint']
                and digest(canonical_json({**before, 'comment': entry['new_comment']})) == entry['after_fingerprint'],
                'Journal preimage changed')
        require(entry.get('status') in ('prepared', 'pending', 'verified')
                and entry.get('rollback_status') in (None, 'pending', 'verified'), 'Invalid journal transition')
    return record, reviewed


def inspect_rows(record, snapshot, metadata):
    require(isinstance(snapshot, dict) and isinstance(snapshot.get('activities'), list), 'Invalid snapshot')
    validate_snapshot(snapshot, {**metadata, 'count': len(snapshot['activities'])})
    actual = {row['id']: row for row in snapshot['activities']}
    result = {}
    for row_id, entry in record['rows'].items():
        row = actual.get(row_id)
        before = entry['preimage']
        if row is not None and 'updatedAt' in before:
            # Fingerprints retain the original timestamp for old journals too.
            # Exact observed timestamps remain in postimages, never in a PUT.
            try:
                if instant(row.get('updatedAt')) >= instant(before['updatedAt']):
                    row = {**row, 'updatedAt': before['updatedAt']}
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
        fingerprint = digest(canonical_json(row))
        state = ('converted' if fingerprint == entry['after_fingerprint'] else
                 'original' if fingerprint == entry['before_fingerprint'] else
                 'absent' if row is None else 'changed')
        pending = entry.get('rollback_status') == 'pending' or (
            entry.get('rollback_status') is None and entry['status'] == 'pending')
        result[row_id] = 'uncertain:' + state if pending else state
    return result


def inspect(journal, manifest, manifest_sha256, snapshot, snapshot_sha256):
    record, reviewed = migration_journal(journal, manifest, manifest_sha256)
    return inspect_rows(record, exact_json(read_evidence(Path(snapshot), snapshot_sha256)), reviewed['snapshot'])


def hydrate_row(row):
    return {**row, **{key: Decimal(str(row[key])) for key in ('quantity', 'unitPrice', 'fee')}}


def rollback(journal, manifest, manifest_sha256, approval, approval_sha256, host, token):
    from contextlib import ExitStack
    import time
    from ghostfolio_degiro_sync.journal import account_journal
    path = safe_path(Path(journal))
    permit_bytes = read_evidence(Path(approval), approval_sha256)
    reviewed_bytes = read_evidence(Path(manifest), manifest_sha256)
    descriptor = journal_lock(path, {safe_path(Path(approval)): permit_bytes, safe_path(Path(manifest)): reviewed_bytes})
    try:
        journal_bytes = path.read_bytes()
        record, reviewed = migration_journal(path, manifest, manifest_sha256)
        permit = keyed_yaml(permit_bytes)
        require(permit.get('journal_sha256') == digest(journal_bytes)
                and permit.get('host') == record['host'] == host
                and permit.get('state_dir') == record['state_dir'], 'Rollback binding changed')
        # Validate authority before authentication or fresh reads. The selected
        # count is checked again after independent settlement and exact readback.
        qualified_approval({**permit, 'write_count': len(record['rows'])}, reviewed,
            manifest_sha256, host, [hydrate_row(entry['preimage']) for entry in record['rows'].values()], 'rollback')
        with ExitStack() as stack:
            for source, target in sorted(record['scope'].items()):
                state = stack.enter_context(account_journal({'state_dir': permit['state_dir'],
                    'ghost_host': host, 'source_account': source, 'target_account': target['id']}))
                require(state['document']['pending'] is None, 'Unsettled normal synchronization intent')
            token = maintenance_token(host, token)
            def fresh():
                result = maintenance_request('GET', host, token)
                inspect_rows(record, result, reviewed['snapshot'])
                require(read_evidence(Path(approval), approval_sha256) == permit_bytes
                        and read_evidence(Path(manifest), manifest_sha256) == reviewed_bytes, 'Rollback evidence changed')
                require(implementation_hashes() == reviewed['implementation'], 'Implementation changed')
                return result
            snapshot = fresh()
            states = inspect_rows(record, snapshot, reviewed['snapshot'])
            selected, resolved = [], []
            settlements = permit.get('settlements', {})
            require(isinstance(settlements, dict), 'Invalid request settlements')
            for row_id, entry in record['rows'].items():
                state = states[row_id]
                reverse = entry.get('rollback_status')
                pending = reverse == 'pending' or reverse is None and entry['status'] == 'pending'
                if pending:
                    proof = settlements.get(row_id, {})
                    require(isinstance(proof, dict) and proof.get('direction') == ('rollback' if reverse else 'apply')
                            and proof.get('outcome') in ('completed', 'cancelled')
                            and proof.get('independent') is True and text(proof.get('evidence_ref')),
                            'Pending request lacks independent settlement proof')
                    state = state.removeprefix('uncertain:')
                    expected_state = ('original' if reverse else 'converted') if proof['outcome'] == 'completed' else (
                        'converted' if reverse else 'original')
                    require(state == expected_state, 'Request settlement contradicts readback')
                    resolved.append((entry, reverse, proof))
                elif reverse == 'verified' or entry['status'] == 'prepared':
                    require(state == 'original', 'Unchanged original context required')
                else:
                    require(state == 'converted', 'Unchanged converted context required')
                if state == 'converted':
                    selected.append(row_id)
            batch, pause = qualified_approval(permit, reviewed, manifest_sha256, host,
                [hydrate_row(record['rows'][row_id]['preimage']) for row_id in selected], 'rollback')
            expected = {row['id']: row for row in snapshot['activities']}
            def check(written=None):
                actual = {row['id']: row for row in fresh()['activities']}
                if written is not None:
                    expected[written] = owned_readback(expected[written], actual.get(written))
                require(actual.keys() == expected.keys() and all(canonical_json(actual[key]) == canonical_json(value)
                    for key, value in expected.items()), 'Rollback protected context changed')
            check()
            for entry, reverse, proof in resolved:
                entry['settlement'] = proof
                if reverse:
                    if proof['outcome'] == 'completed':
                        entry['rollback_status'] = 'verified'
                    else:
                        del entry['rollback_status']
                else:
                    entry['status'] = 'verified' if proof['outcome'] == 'completed' else 'prepared'
            for index, row_id in enumerate(selected):
                if index and index % batch == 0:
                    time.sleep(pause)
                check()
                entry = record['rows'][row_id]
                payload = comment_payload(expected[row_id], entry['old_comment'])
                entry.update(rollback_status='pending', rollback_request_body_sha256=digest(numeric_json(payload)))
                record.update(status='rollback_in_progress', rollback_approval_sha256=approval_sha256)
                persist(path, record)
                maintenance_request('PUT', host, token, row_id, payload)
                expected[row_id] = {**expected[row_id], 'comment': entry['old_comment']}
                check(row_id)
                entry['rollback_postimage'] = expected[row_id]
                entry['rollback_status'] = 'verified'
                persist(path, record)
            record['status'] = 'rolled_back'
            persist(path, record)
    finally:
        os.close(descriptor)
