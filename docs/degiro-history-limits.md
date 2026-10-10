# DEGIRO history reach and request limits

Research date: 2026-10-10. Scope: public primary sources, the installed
`degiro-connector==3.0.36`, its pinned source, and existing operator evidence.
The primary-source investigation made no authenticated broker requests. The
separate operator-requested 2026 YTD read below was performed afterward.

## What is already established

This account has already returned history older than one year. The existing
read-only investigation requested **2000-01-01 through 2026-10-08** in overlapping
366-day windows, then reread the occupied **2019-04-25 through 2026-10-08** interval
in overlapping 90-day windows. The earliest observed movement was **2019-04-25**.
Both widths returned the same 70 complete execution bodies and 1,001 cash rows
with nonzero IDs, excluding only the previously characterized window-derived
cash `balance`. This establishes observed reach on this account; it does not
establish account inception, unlimited retention, or completeness of all financial
history. [Existing operator evidence](source-contract.md#extended-historical-read-only-characterization)

The legacy 2019/2020 monetary-fund NAV records differ between window widths and
share ID `0`; the historical CSV comparison also has unresolved discrepancies.
Retrieving these records does not make them safe to import or certify historical
cost basis. Florent declined further historical reconciliation without independent
records. [Existing operator evidence](source-contract.md#extended-historical-read-only-characterization),
[historical evidence limits](historical-fund-evidence.md)

The later successful prospective DRY_RUN used **2026-10-03 through 2026-10-10**.
That start was an agent-selected characterization interval covering a recent
cash movement after an empty-period CSV request failed; it was not an
operator-approved final synchronization horizon. The private acceptance report
under `tmp/c14-real-remotegets-approved-20261010/` records zero post-cutover activity
proposals and no financial writes. This recent validation cannot replace the
older reach observations or define the final period policy.

## Fresh 2026 YTD read

An explicitly requested read-only collection on 10 October queried **2026-01-01
through 2026-10-10**, using four overlapping 90-day windows and a separate French
CSV statement. The existing `--read-only` command exited successfully and returned
**3 executed transactions and 58 cash movements**, with no Ghostfolio request or
financial write. Executions run from 9 January through 5 August; cash movements
run from 2 January through 6 October. Private source and comparison evidence is
retained under `tmp/ytd-readonly-20261010/`.

The CSV also has 58 dated rows. An exact comparison matches 57 API rows; the
single remaining pair, dated **2026-08-05**, differs only by **0.01** in movement
amount. All other compared fields agree. The initial strict equality check
refused this interval. Florent subsequently approved the one-cent execution
rounding on10 October. The retained capture confirms a unique execution and
signed quantity-times-price gross corroboration: its declared total retains
subcent precision, while the two cash views differ by0.01. After the bounded
comparison change, all58statement rows and all3execution/cash relations pass
without modifying any capture or making a network request. This does not validate
a different cutover, full prospective YTD account state, historical completeness
or a historical import policy. The operational period remains to be decided.
[Statement comparison contract](source-contract.md#history-and-statement-comparison),
[current strict check](../degiro_to_ghostfolio.py)

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
| Orders | Separate order-history endpoint. | Existing account observations returned no orders in a year containing executions; orders do not establish execution completeness. |

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

## What the current script actually requests

These are **repository policy choices**, not DEGIRO limits:

- History reads default to 90-day windows with one overlapping boundary day.
  Accepted window sizes are 2 through 366 days, with at most 120 windows.
  Each window fetches executed transactions and cash movements; optional orders
  add a third request. Product metadata, current account information, holdings
  and a CSV statement are separate requests as required by the mode.
  [Adapter implementation](../degiro_to_ghostfolio.py)
- Full-history `--sync` defaults to `LOOKBACK_DAYS=90`, allows an environment
  lookback of 2 through 366 days, and accepts explicit dates. This numeric
  environment guard does not mean the broker retains only a year.
  [Adapter CLI](../degiro_to_ghostfolio.py)
- Prospective `--sync` replaces the requested start with the opening capture's
  pinned `from_date`. It rereads from that fixed start through at least today's
  Europe/Zurich date. A recent CLI start or cron lookback cannot shorten it.
  With the latest opening evidence, that means **3 October 2026 onward** until
  the opening policy/evidence is explicitly replaced. The capture command
  defaults to yesterday and accepts an explicit `--from-date`.
  [Prospective run contract](prospective-sync.md),
  [capture implementation](../scripts/prepare_cutover.py)
- The adapter uses one login per collection, sequential requests, connect/read
  timeouts of 10/30 seconds, no automatic retries and a bounded logout attempt.
  It fails on redirect/maintenance or failed endpoint calls. These are local
  safeguards, not published server quotas. [Adapter transport](../degiro_to_ghostfolio.py)

The historical contract note describes the collector/runtime as it behaved on
8 October. The current implementation now accepts **exactly** cash-overview
`data: {}` as an empty cash collection. Other malformed envelopes still fail.
An empty recent CSV interval returned HTTP 500 during the later characterization;
a wider recent interval succeeded. This does not establish a universal rule that
empty periods fail or that widening a period is always necessary.
[Current parser](../degiro_to_ghostfolio.py),
[capture operational guidance](prospective-sync.md)

## Input to the later final specification

Separate three decisions: the historical period to inspect, the date after which
new events are eligible for synchronization, and how much source history each
scheduled run rereads. A successful DRY_RUN does not choose those policies.
The final horizon remains an operator decision; the one-week characterization
start must not silently become an approved operational default.

Reuse the existing 2019-to-current read-only archive before collecting anything
else. If a particular proposed horizon needs fresh evidence, later authorize a
bounded read-only comparison of that interval with smaller overlapping windows
and the separate CSV statement. Compare stable IDs and full financial fields,
preserve individual responses privately, and distinguish empty responses,
transport failures and mismatches. Stop on authentication challenges or uncertain
responses rather than retrying aggressively. This can characterize the requested
interval but cannot establish an undocumented global broker maximum.
[Existing archive and comparisons](source-contract.md#extended-historical-read-only-characterization),
[read-only command and evidence limits](read-only.md)

This research changes no runtime policy, opening manifest, production schedule,
historical import authority, or financial-write authorization.
