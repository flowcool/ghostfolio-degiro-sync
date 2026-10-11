# DEGIRO history reach and request limits

This reference distinguishes pinned connector behavior from undocumented broker
limits. The community default is a rolling90-day contract; private account
characterization and captures are not distributed here.

## Broker guarantees versus connector behavior

DEGIRO's official help says it currently does not offer an API for connecting
an account to another application. The connector accesses the trading platform's
private endpoints; its behavior is not a published broker API contract.
No authoritative maximum lookback, maximum request span, result cap, pagination
contract, or requests-per-minute allowance was established in the sources
examined. **Unknown means unverified, not unlimited.**
[DEGIRO official API help](https://www.degiro.com/uk/helpdesk/trading-platform/does-degiro-offer-api)

The inspected connector source is pinned to commit
`22691b5e355094ba8b52c364bb3a5f33d9cc1bbc`; the installed version and source
provenance are recorded locally. [Connector provenance](connector-provenance.yaml)

| Feed | Connector behavior at the pinned commit | Limit established |
| --- | --- | --- |
| Executed transactions | One GET to `/portfolio-reports/secure/v4/transactions`, with `fromDate`, `toDate`, and `groupTransactionsByOrder`; the adapter explicitly uses `false`. | No age/span cap, page size, cursor, offset, or pagination loop in this request path. |
| Cash movements | One GET to `/portfolio-reports/secure/v6/accountoverview`, with `fromDate` and `toDate`; raw `data.cashMovements` is retained by the adapter. | No age/span cap or pagination implemented in this request path. |
| Cash statement | One GET to `/portfolio-reports/secure/v3/cashAccountReport/{format}`, with country, language and dates; formats include CSV, HTML, PDF and XLS. | No age/span cap or pagination implemented in this request path. |
| Orders | Separate order-history endpoint. | Order snapshots do not establish executed-history completeness. |

Sources: pinned connector [endpoint constants](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/core/constants/urls.py),
[transaction request/action](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/actions/action_get_transactions_history.py),
[transaction models](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/models/transaction.py),
[cash overview action](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/actions/action_get_account_overview.py),
[cash report action](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/actions/action_get_account_report.py),
[account request models](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/models/account.py),
and [observed order-history limitation](source-contract.md#history-and-statement-comparison).

The date models serialize calendar dates as `DD/MM/YYYY` without imposing a
lookback or span validator. A single connector call does not guarantee that the
server returns every row. The existing same-day observation supports inclusive
boundaries for that observed day, not a universal broker guarantee.
[Transaction models](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/models/transaction.py),
[account models](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/models/account.py),
[boundary observation](source-contract.md#history-and-statement-comparison)

The connector README describes a trading connection timeout of 30 minutes,
refreshed by use; its API class also sets a client-side `TRADING_TIMEOUT = 1800`.
This is connector documentation and a client expiration model, not a verified
broker session SLA or a history retention limit. No numeric rate allowance was
found in the inspected history paths. [Connector timeout documentation](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/README.md#38-is-there-a-timeout-),
[API implementation](https://github.com/Chavithra/degiro-connector/blob/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc/src/degiro_connector/trading/api.py)

## Adapter bounds

- Collection windows span2–366days, at most120windows, with overlap validation.
- Community Compose sets rolling90days through broker-local today; outage gaps
  require an explicit earlier catch-up start. Historical completeness/basis remain unverified.
- Developer full-history mode preserves its completeness gate; prospective mode
  rereads from the account-specific pinned opening capture, never a universal date.
- Each collection uses one broker login, sequential bounded requests, no retries,
  strict transport and a bounded logout attempt. These are local safeguards,
  not a published server quota. Empty recent statements may fail; fail closed.

See [source contract](source-contract.md), [prospective contract](prospective-sync.md)
and [read-only capture](read-only.md). Read success alone does not approve import,
opening state, historical completeness or financial writes.
