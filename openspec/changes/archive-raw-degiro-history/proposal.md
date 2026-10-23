# Proposal

## Why

The current read-only command rejects legacy cash-fund records before it saves a snapshot. An operator cannot retain a new copy of the full requested history with that command.

## What Changes

- Add an explicit history archive command outside the shipped runtime image. Run its versioned script with the pinned connector image.
- Save each successful financial response before accounting checks. Keep original response bytes, request dates and hashes in private files.
- Use one vault retrieval and broker login per archive. Keep bounded requests, no retries, logout and secret-free diagnostics.
- Keep incomplete archives after failure. Report requested coverage separately from proven completeness.
- Add an offline inventory that identifies exclusions and reasons without discarding their source evidence. Unsupported or ambiguous required input keeps imports blocked.

Observed event scope comes from the saved 2000–2026 broker response collection inspected on 2026-10-23. These names describe source evidence, not new import support.

| Source event | Archive scope | Import scope |
| --- | --- | --- |
| BUY (`B`) | Retain | Unchanged |
| SELL (`S`) | Retain | Unchanged |
| `TRANSACTION` | Retain | Unchanged |
| `CASH_TRANSACTION` | Retain | Unchanged |
| `FLATEX_CASH_SWEEP` | Retain | Unchanged |
| `COMPENSATION_BOOKING` | Retain | Unchanged |
| `CASH_FUND_NAV_CHANGE` | Retain | Still unsupported |
| `CASH_FUND_TRANSACTION` | Retain | Still unsupported |
| Unknown or malformed financial rows | Retain with the original response | No new permission |

## Capabilities

### New Capabilities

- `degiro-history-archive`: retain a private, source-bound archive without financial normalization or Ghostfolio access.

### Modified Capabilities

None.

## Impact

Add `scripts/archive_degiro_history.py`, offline regression tests and the required read-only user guide. Reuse the installed package's vault and bounded broker transport. No dependency, runtime image, immutable core or normal synchronization change is planned.

## Non-goals

No financial writes, silent input filtering, supported legacy accounting, completeness certification, archive-to-sync override, production deployment or lab qualification. The existing whole-account refusal remains in force. Any change to exclusion policy requires its own approved scope.
