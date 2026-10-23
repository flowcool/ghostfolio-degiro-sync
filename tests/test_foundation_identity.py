"""Dual-reader identities and complete destination ownership use synthetic rows."""
from copy import deepcopy

import pytest

from ghostfolio_degiro_sync import ghostfolio, identity
from test_degiro_sync import NOW, TARGET, activity_row, snapshot


def candidate(kind='TRADE', activity_type='BUY', comment=None):
    return {'accountId': 'target-a', 'comment': comment or f'DEGIRO#123:{kind}:10',
        'type': activity_type, 'symbol': 'TEST', 'dataSource': 'YAHOO',
        'date': '2026-01-01T00:00:00Z', 'currency': 'USD', 'quantity': 1, 'unitPrice': 2, 'fee': 0}


@pytest.mark.parametrize('kind,activity_type', [('TRADE', 'BUY'), ('TRADE', 'SELL'),
    ('DIVIDEND', 'DIVIDEND'), ('FEE', 'FEE'), ('INTEREST', 'INTEREST'), ('COMPENSATION', 'INTEREST')])
def test_legacy_and_v1_resolve_same_source_identity(kind, activity_type):
    assert identity.parse_identity(f'DEGIRO#123:{kind}:10', activity_type) == ('123', kind, '10')
    assert identity.parse_identity(f'DEGIRO#v1#123:{kind}:10', activity_type) == ('123', kind, '10')
    assert identity.parse_identity(f'DEGIRO#v1#124:{kind}:10', activity_type) != ('123', kind, '10')


def test_mixed_history_suppresses_exact_event_and_rejects_duplicate_claims():
    activity = candidate()
    stored = {**activity, 'comment': 'DEGIRO#v1#123:TRADE:10'}
    assert ghostfolio.pending_activities([activity], [stored], TARGET, '123') == []
    with pytest.raises(RuntimeError, match='Duplicate'):
        ghostfolio.pending_activities([activity], [stored, activity], TARGET, '123')
    stored['unitPrice'] = 3
    with pytest.raises(RuntimeError, match='changed financial'):
        ghostfolio.pending_activities([activity], [stored], TARGET, '123')


def test_global_ownership_refuses_target_remapping_without_borrowing_holdings():
    activity = candidate()
    stored = activity_row({**activity, 'accountId': 'old-target', 'comment': 'DEGIRO#v1#123:TRADE:10'})
    rows, holdings = ghostfolio.index_existing_activities({'activities': [stored], 'count': 1}, TARGET, now=NOW)
    assert holdings == {}
    with pytest.raises(RuntimeError, match='another target'):
        ghostfolio.pending_activities([activity], rows, TARGET, '123')
    stored['isExcluded'] = True
    assert ghostfolio.index_existing_activities({'activities': [stored], 'count': 1}, TARGET, now=NOW)[1] == {}


@pytest.mark.parametrize('comment', ['DEGIRO#v2#123:TRADE:10', 'DEGIRO#v1#123:TRADE:0',
    'DEGIRO#v1#123:TRADE:10 ', 'DEGIRO#v1#123:FEE:10', 'DEGIRO#v1#123:TRADE:é'])
def test_reserved_invalid_comment_fails_even_outside_target(comment):
    row = activity_row(candidate(comment=comment))
    row['accountId'] = 'other-target'
    with pytest.raises(RuntimeError):
        ghostfolio.index_existing_activities({'activities': [row], 'count': 1}, TARGET, now=NOW)


@pytest.mark.parametrize('size,valid', [(1999, True), (2000, True), (2001, False)])
def test_ascii_comment_length_boundaries(size, valid):
    prefix = 'DEGIRO#v1#123:TRADE:'
    comment = prefix + '1' * (size - len(prefix))
    if valid:
        assert identity.parse_identity(comment, 'BUY') == ('123', 'TRADE', comment[len(prefix):])
    else:
        with pytest.raises(RuntimeError):
            identity.parse_identity(comment, 'BUY')


def test_new_trade_writer_uses_generation_one_without_changing_source_id():
    assert identity.execution_comment('123', '10') == 'DEGIRO#v1#123:TRADE:10'


def test_writer_first_repeat_and_mixed_history_preserve_all_existing_rows(snapshot):
    from ghostfolio_degiro_sync import sync
    from test_degiro_sync import MAPPING, QUOTES, opening_holding
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': True}
    body = {'activities': [opening_holding()], 'count': 1}
    first = sync.select_account_activities(config, snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
    assert all(row['comment'].startswith('DEGIRO#v1#') for row in first.selection.proposals)
    for index, proposal in enumerate(first.selection.proposals):
        row = activity_row(dict(proposal), str(index))
        if index % 2 == 0:
            row['comment'] = row['comment'].replace('DEGIRO#v1#', 'DEGIRO#')
        body['activities'].append(row)
    body['count'] = len(body['activities'])
    before = deepcopy(body)
    second = sync.select_account_activities(config, snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
    assert second.selection.proposals == () and body == before


def test_explicit_live_request_forced_to_simulation_sends_no_mutation(snapshot, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    import requests
    from ghostfolio_degiro_sync import degiro, sync
    from test_degiro_sync import MAPPING, QUOTES, configure, opening_holding, response
    configure(monkeypatch, tmp_path, '0')
    monkeypatch.setenv('TZ', 'invalid-zone')
    now = datetime.now(timezone.utc)
    snapshot['fetch_started_at'] = (now - timedelta(seconds=2)).isoformat()
    snapshot['fetched_at'] = now.isoformat()
    monkeypatch.setattr(degiro, 'read_degiro', lambda *args: snapshot)
    proposals = sync.select_account_activities({'source_account': '123', 'target_account': 'target-a',
        'dry_run': True}, snapshot, TARGET, {'activities': [opening_holding()], 'count': 1},
        MAPPING, QUOTES, now=now).selection.proposals
    rows = [opening_holding()]
    for index, proposal in enumerate(proposals):
        row = activity_row(dict(proposal), str(index))
        if index == 0:
            row['comment'] = row['comment'].replace('DEGIRO#v1#', 'DEGIRO#')
        rows.append(row)
    calls = []
    def send(session, request, **kwargs):
        calls.append(request.method)
        assert request.method == 'GET'
        return response(TARGET if request.path_url.endswith('/target-a') else {'activities': rows, 'count': len(rows)})
    monkeypatch.setattr(requests.Session, 'send', send)
    result = sync.run_sync(now.date(), now.date())
    assert result['dry_run'] and result['accepted'] == [] and result['proposed'] == []
    assert calls == ['GET', 'GET']
