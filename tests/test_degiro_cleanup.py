"""Exact broker ownership selection; no deletion or HTTP implementation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

import degiro_to_ghostfolio as adapter
from scripts import cleanup_degiro
from test_degiro_sync import TARGET, MAPPING, QUOTES, activity_row, opening_holding, snapshot


def inputs(snapshot):
    activities = adapter.normalize_trades(snapshot, TARGET['id'], MAPPING, QUOTES)
    activities += adapter.normalize_dividends(snapshot, TARGET['id'], MAPPING, QUOTES)
    activities += adapter.normalize_fees(snapshot, TARGET['id'])
    manifest = {'source_account': '123', 'target_account': TARGET['id'],
        'activities': {a['comment']: a for a in activities}}
    rows = [opening_holding()] + [activity_row(a, str(i)) for i, a in enumerate(activities)]
    return {'activities': rows, 'count': len(rows)}, manifest


def test_preflight_selects_only_exact_manifest_ids(snapshot):
    body, manifest = inputs(snapshot)
    manual = deepcopy(body['activities'][0])
    manual['id'] = 'manual-keep'
    body['activities'].append(manual)
    other = deepcopy(manual)
    other.update(id='foreign-keep', accountId='foreign', comment='IBKR#123')
    body['activities'].append(other)
    body['count'] = len(body['activities'])
    result = adapter.cleanup_preflight(body, manifest)
    assert set(result['activity_ids'].values()) == {'0', '1', '2'}
    assert len(result['snapshot_sha256']) == 64


@pytest.mark.parametrize('mutation', ['missing', 'changed', 'foreign', 'duplicate', 'count', 'namespace', 'comment', 'extra', 'redacted'])
def test_unproved_cleanup_never_produces_ids(snapshot, mutation):
    body, manifest = inputs(snapshot)
    identity = next(iter(manifest['activities']))
    if mutation == 'missing':
        body['activities'].pop()
        body['count'] -= 1
    elif mutation == 'changed':
        body['activities'][-1]['fee'] += 1
    elif mutation == 'foreign':
        body['activities'][-1]['accountId'] = 'foreign'
    elif mutation == 'duplicate':
        body['activities'].append(deepcopy(body['activities'][-1]))
        body['count'] += 1
    elif mutation == 'count':
        body['count'] += 1
    elif mutation == 'namespace':
        manifest['source_account'] = '456'
    elif mutation == 'comment':
        manifest['activities'][identity]['comment'] = None
    elif mutation == 'extra':
        manifest['activities'][identity]['password'] = 'FAKE-SENTINEL'
    else:
        body['activities'][-1]['quantity'] = None
    with pytest.raises(RuntimeError):
        adapter.cleanup_preflight(body, manifest)


def test_cli_outputs_private_new_file_and_never_overwrites(snapshot, tmp_path, capsys):
    body, manifest = inputs(snapshot)
    source, expected, output = (tmp_path / name for name in ('snapshot.json', 'expected.yaml', 'ids.yaml'))
    source.write_text(json.dumps(body))
    expected.write_text(yaml.safe_dump(manifest))
    argv = ['--snapshot', str(source), '--manifest', str(expected), '--output', str(output)]
    assert cleanup_degiro.main(argv) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    previous = output.read_bytes()
    assert cleanup_degiro.main(argv) == 1 and output.read_bytes() == previous
    assert 'DEGIRO#' not in capsys.readouterr().out
