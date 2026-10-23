"""Pure selection and confirmed-result boundaries use synthetic account data."""
from copy import deepcopy
from decimal import Decimal

import pytest

from ghostfolio_degiro_sync import ghostfolio, sync
from test_degiro_sync import MAPPING, NOW, QUOTES, TARGET, opening_holding, snapshot


def test_selection_has_no_dispatch_and_preserves_input(snapshot):
    body = {'activities': [opening_holding()], 'count': 1}
    original = deepcopy((snapshot, body))
    plan = sync.select_account_activities(
        {'source_account': '123', 'target_account': 'target-a', 'dry_run': True},
        snapshot, TARGET, body, MAPPING, QUOTES, now=NOW)
    assert [row['type'] for row in plan.selection.proposals] == ['SELL', 'DIVIDEND', 'FEE']
    assert plan.selection.holdings == (('target-a', 'TEST', Decimal('10')),)
    assert plan.selection.rejected == () and plan.selection.deferred == ()
    assert (snapshot, body) == original
    assert plan.cash == 12.3


def test_confirmed_rows_only_update_disposable_holdings():
    holdings = {('target-a', 'TEST'): Decimal('2')}
    buy = {'accountId': 'target-a', 'symbol': 'TEST', 'type': 'BUY', 'quantity': '3'}
    assert ghostfolio.record_accepted_activities([], holdings) == holdings
    assert ghostfolio.record_accepted_activities([buy], holdings) == {('target-a', 'TEST'): Decimal('5')}
    assert holdings == {('target-a', 'TEST'): Decimal('2')}


@pytest.mark.parametrize('change', ['incomplete', 'masked', 'future'])
def test_pure_index_refuses_unsafe_context(change):
    row = opening_holding()
    body = {'activities': [row], 'count': 1}
    if change == 'incomplete':
        body['count'] = 2
    elif change == 'masked':
        row['quantity'] = None
    else:
        row['date'] = '2026-10-09T00:00:00Z'
    with pytest.raises(RuntimeError):
        ghostfolio.index_existing_activities(body, TARGET, now=NOW)


def test_selection_uses_fixed_clock_for_future_candidates(snapshot):
    from datetime import datetime, timezone
    snapshot['fetch_started_at'] = '2025-01-01T00:00:00Z'
    snapshot['fetched_at'] = '2025-01-01T00:00:00Z'
    with pytest.raises(RuntimeError, match='Future DEGIRO candidate'):
        sync.select_account_activities(
            {'source_account': '123', 'target_account': 'target-a', 'dry_run': True},
            snapshot, TARGET, {'activities': [opening_holding()], 'count': 1}, MAPPING, QUOTES,
            now=datetime(2025, 1, 1, tzinfo=timezone.utc))
