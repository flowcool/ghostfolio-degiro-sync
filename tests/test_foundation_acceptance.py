"""Exact accepted subsets, profile rewrites and durable uncertainty."""
from copy import deepcopy
import json

import pytest
import requests

from ghostfolio_degiro_sync import accounting, ghostfolio, journal, sync
from test_degiro_sync import NOW, TARGET, MAPPING, QUOTES, activity_row, opening_holding, snapshot

UUID = '12345678-1234-4234-8234-123456789abc'


def fee(price=0):
    return {'accountId': 'target-a', 'comment': 'DEGIRO#123:FEE:104', 'dataSource': 'MANUAL',
        'symbol': 'GF_DEGIRO_123_SERVICE_EUR', 'type': 'FEE', 'date': '2026-01-01T00:00:00Z',
        'currency': 'EUR', 'quantity': 1, 'unitPrice': price, 'fee': 0}


def test_exact_uuid_acceptance_preserves_source_and_zero_values():
    proposal = fee()
    accepted, profiles = ghostfolio.prove_accepted_subset([proposal], [{**proposal, 'symbol': UUID}])
    assert accepted == [proposal]
    assert profiles['DEGIRO#123:FEE:104']['returned'] == UUID
    assert profiles['DEGIRO#123:FEE:104']['requested'] == proposal['symbol']
    row = activity_row({**proposal, 'symbol': UUID})
    rows, bound = ghostfolio.bind_existing_profiles([row | {'symbol': UUID, 'dataSource': 'MANUAL'}], [proposal], {})
    assert rows[0]['symbol'] == proposal['symbol']
    assert ghostfolio.pending_activities([proposal], rows, TARGET, '123') == []
    assert bound == profiles


@pytest.mark.parametrize('change', ['amount', 'date', 'currency', 'source', 'symbol', 'type'])
def test_profile_mapping_requires_exact_identity_financial_and_profile_evidence(change):
    proposal = fee()
    created = {**proposal, 'symbol': UUID}
    if change == 'amount': created['unitPrice'] = 1
    if change == 'date': created['date'] = '2026-01-02T00:00:00Z'
    if change == 'currency': created['currency'] = 'USD'
    if change == 'source': created['comment'] = 'DEGIRO#124:FEE:104'
    if change == 'symbol': created['symbol'] = 'unproved-name'
    if change == 'type': created['dataSource'] = 'YAHOO'
    with pytest.raises(RuntimeError):
        ghostfolio.prove_accepted_subset([proposal], [created])


def test_missing_source_or_durable_mapping_does_not_guess_uuid():
    row = {**fee(), 'symbol': UUID}
    with pytest.raises(RuntimeError, match='Unproved MANUAL'):
        ghostfolio.bind_existing_profiles([row], [], {})
    accepted, profiles = ghostfolio.prove_accepted_subset([fee()], [row])
    assert ghostfolio.bind_existing_profiles([row], [], profiles)[0][0]['symbol'] == fee()['symbol']
    row['fee'] = 1
    with pytest.raises(RuntimeError):
        ghostfolio.bind_existing_profiles([row], [], profiles)


def test_partial_acceptance_retains_exact_subset_and_pending_fence(snapshot, tmp_path):
    tmp_path.chmod(0o700)
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False,
        'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path)}
    posted = []
    def partial(batch):
        posted.extend(batch)
        return [deepcopy(batch[0])], False
    with pytest.raises(RuntimeError, match='cash blocked'):
        sync.synchronize_account(config, snapshot, TARGET,
            {'activities': [opening_holding()], 'count': 1}, MAPPING, QUOTES,
            partial, lambda *args: pytest.fail('cash PUT'), now=NOW)
    with journal.account_journal(config) as state:
        pending = state['document']['pending']
        assert len(pending['accepted']) == 1
        assert pending['accepted'][0] == posted[0]
        assert 'coverage' not in state['document']
        assert not state['document']['resolved']


@pytest.mark.parametrize('kind,price', [('FEE', 0), ('INTEREST', 0)])
def test_real_core_accepts_zero_manual_uuid_with_exact_association(monkeypatch, kind, price):
    import ghostfolio_core as core
    from test_degiro_sync import response
    proposal = fee(price)
    proposal['type'] = kind
    proposal['comment'] = f'DEGIRO#123:{kind}:104'
    if kind == 'INTEREST':
        proposal['symbol'] = 'GF_DEGIRO_123_FLATEX_INTEREST_EUR'
    created = activity_row({**proposal, 'symbol': UUID})
    monkeypatch.setattr(core.requests, 'post', lambda *args, **kwargs: response({'activities': [created]}, 201))
    returned, ok = core.ghost_import_activities({'ghost_host': 'http://localhost:3333',
        'ghost_token': 'synthetic', 'dry_run': False}, [proposal])
    accepted, profiles = ghostfolio.prove_accepted_subset([proposal], returned)
    assert ok and accepted == [proposal]
    assert profiles[proposal['comment']]['returned'] == UUID


def test_native_nullable_currency_import_preserves_raw_evidence_and_repeat_identity(monkeypatch):
    import ghostfolio_core as core
    proposal = {**fee(), 'type': 'INTEREST', 'comment': 'DEGIRO#123:INTEREST:104',
        'symbol': 'GF_DEGIRO_123_FLATEX_INTEREST_EUR'}
    created = activity_row({**proposal, 'symbol': UUID, 'currency': None})
    created['assetProfile']['currency'] = 'EUR'
    body = {'activities': [created], 'count': 1}
    raw = json.dumps(body).encode()
    reply = requests.Response()
    reply.status_code = 201
    reply._content = raw
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kwargs: reply)
    config = {'ghost_host': 'http://localhost:3333', 'ghost_token': 'synthetic', 'dry_run': False}
    with ghostfolio.ghost_transport(config, TARGET):
        returned, ok = core.ghost_import_activities(config, [proposal])
    accepted, profiles = ghostfolio.prove_accepted_subset([proposal], returned)
    assert ok and accepted == [proposal]
    assert profiles[proposal['comment']]['returned'] == UUID
    rows, _ = ghostfolio.index_existing_activities(body, TARGET, now=NOW)
    rows, bound = ghostfolio.bind_existing_profiles(rows, [proposal], profiles)
    assert ghostfolio.pending_activities([proposal], rows, TARGET, '123') == []
    assert bound == profiles
    assert reply.content == raw
    assert body['activities'][0]['currency'] is None


@pytest.mark.parametrize('profile_currency', [None, '', 'GBp', 123])
def test_nullable_currency_without_supported_profile_stays_uncertain(monkeypatch, profile_currency):
    import ghostfolio_core as core
    proposal = {**fee(), 'type': 'INTEREST', 'comment': 'DEGIRO#123:INTEREST:104',
        'symbol': 'GF_DEGIRO_123_FLATEX_INTEREST_EUR'}
    created = activity_row({**proposal, 'symbol': UUID, 'currency': None})
    if profile_currency is not None:
        created['assetProfile']['currency'] = profile_currency
    reply = requests.Response()
    reply.status_code = 201
    reply._content = json.dumps({'activities': [created]}).encode()
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kwargs: reply)
    config = {'ghost_host': 'http://localhost:3333', 'ghost_token': 'synthetic', 'dry_run': False}
    with ghostfolio.ghost_transport(config, TARGET):
        assert core.ghost_import_activities(config, [proposal]) == ([], False)
    assert config['_uncertain_import_accounts'] == {'target-a'}
    with pytest.raises(RuntimeError, match='Unverified .* (currency|representation)'):
        ghostfolio.index_existing_activities({'activities': [created], 'count': 1}, TARGET, now=NOW)


def test_explicit_activity_currency_overrides_profile_currency(monkeypatch):
    import ghostfolio_core as core
    proposal = fee()
    created = activity_row({**proposal, 'symbol': UUID})
    created['assetProfile']['currency'] = 'USD'
    reply = requests.Response()
    reply.status_code = 201
    reply._content = json.dumps({'activities': [created]}).encode()
    monkeypatch.setattr(requests.Session, 'send', lambda *args, **kwargs: reply)
    config = {'ghost_host': 'http://localhost:3333', 'ghost_token': 'synthetic', 'dry_run': False}
    with ghostfolio.ghost_transport(config, TARGET):
        returned, ok = core.ghost_import_activities(config, [proposal])
    assert ok and returned[0]['currency'] == 'EUR'
    rows, _ = ghostfolio.index_existing_activities({'activities': [created], 'count': 1}, TARGET, now=NOW)
    assert rows[0]['currency'] == 'EUR'


def test_positive_import_recovery_uses_exact_inherited_profile_currency(tmp_path):
    tmp_path.chmod(0o700)
    proposal = {**fee(), 'type': 'INTEREST', 'comment': 'DEGIRO#123:INTEREST:104',
        'symbol': 'GF_DEGIRO_123_FLATEX_INTEREST_EUR'}
    row = activity_row({**proposal, 'symbol': UUID, 'currency': None})
    row['assetProfile']['currency'] = 'EUR'
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False,
        'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path)}
    with journal.account_journal(config) as state:
        intent = journal.begin_intent(state, 'import', {proposal['comment']: proposal})
        assert journal.verify_import_intent(state, config, {'activities': [row], 'count': 1}, intent) == 1
        assert state['document']['pending']['accepted'] == [proposal]
        assert state['document']['profiles'][proposal['comment']]['returned'] == UUID
        assert row['currency'] is None


@pytest.mark.parametrize('kind', ['BUY', 'DIVIDEND'])
def test_existing_yahoo_rows_inherit_only_their_own_profile_currency(kind):
    source_kind = 'TRADE' if kind == 'BUY' else kind
    proposal = {**fee(), 'type': kind, 'comment': f'DEGIRO#123:{source_kind}:104',
        'symbol': 'TEST', 'dataSource': 'YAHOO', 'currency': 'USD', 'unitPrice': 10}
    row = activity_row({**proposal, 'currency': None})
    row['assetProfile']['currency'] = 'USD'
    rows, _ = ghostfolio.index_existing_activities({'activities': [row], 'count': 1}, TARGET, now=NOW)
    assert rows[0]['currency'] == 'USD'
    assert ghostfolio.pending_activities([proposal], rows, TARGET, '123') == []
    assert row['currency'] is None


def test_recovery_requires_exact_comment_not_only_equivalent_generation(snapshot, tmp_path):
    tmp_path.chmod(0o700)
    config = {'source_account': '123', 'target_account': 'target-a', 'dry_run': False,
        'ghost_host': 'http://localhost:3333', 'state_dir': str(tmp_path)}
    proposal = fee()
    with journal.account_journal(config) as state:
        intent = journal.begin_intent(state, 'import', {proposal['comment']: proposal})
        row = activity_row({**proposal, 'comment': 'DEGIRO#v1#123:FEE:104'})
        with pytest.raises(RuntimeError, match='Complete exact'):
            journal.verify_import_intent(state, config, {'activities': [row], 'count': 1}, intent)
        assert state['document']['pending']['id'] == intent


def test_profile_fingerprint_does_not_change_with_json_number_spelling():
    proposal = fee()
    accepted, profiles = ghostfolio.prove_accepted_subset([proposal], [{**proposal, 'symbol': UUID}])
    observed = {**proposal, 'symbol': UUID, 'quantity': 1.0, 'unitPrice': 0.0, 'fee': 0.0}
    assert ghostfolio.bind_existing_profiles([observed], [], profiles)[0][0]['symbol'] == proposal['symbol']


def test_same_requested_profile_cannot_resolve_to_conflicting_uuids():
    first = fee()
    second = {**first, 'comment': 'DEGIRO#123:FEE:105'}
    with pytest.raises(RuntimeError, match='Conflicting MANUAL'):
        ghostfolio.prove_accepted_subset([first, second], [{**first, 'symbol': UUID},
            {**second, 'symbol': '22345678-1234-4234-8234-123456789abc'}])
