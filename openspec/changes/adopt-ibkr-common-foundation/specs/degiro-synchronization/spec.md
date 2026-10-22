# Spec Delta

## MODIFIED Requirements

### Requirement: Supported deployment

The supported deployment SHALL be `compose.yaml`: settings from ENV, DEGIRO login only from one Bitwarden/Vaultwarden item, exactly one Ghostfolio credential, `SYNC_MODE=rolling`, 90 days, `TZ=Europe/Zurich`. `DRY_RUN` absent, blank or `1`/`true`/`yes`/`on` SHALL simulate; `0`/`false`/`no`/`off` SHALL write; another value SHALL stop before broker access. Empty `CRON` SHALL run once; a `CRON` that is not five numeric fields SHALL stop before the connector starts. `APPRISE_URLS` SHALL send failure alerts without secrets.

The image and CI SHALL use Python 3.14. The image SHALL install the connector package and run `python -m ghostfolio_degiro_sync`. Entrypoint options SHALL retain their meaning. CRON SHALL invoke the installed module with `--sync`. Remove the old script path and document its replacement. Preserve ENV names, supported modes, exit meanings, snapshot formats and recovery commands.

The notification worker SHALL use isolated module execution, bounded lifetime, restricted ENV and stdin payloads. Worker mode SHALL never synchronize or load broker credentials. Developer tools SHALL stay outside the image. Missing or invalid IANA TZ SHALL force simulation before financial dispatch and emit one fixed warning; broker offset timestamps SHALL retain their existing validation.

#### Scenario: Invalid schedule

- **WHEN** `CRON='bad cron' bash entrypoint.sh` runs
- **THEN** it prints `Invalid CRON: expected five numeric schedule fields` and exits 1.

#### Scenario: Installed image and isolated worker

- **WHEN** `.venv/bin/python scripts/smoke_container.py degiro-foundation:check` runs with no network or real credentials
- **THEN** Python 3.14, installed one-off/cron module execution, UID 10001 and read-only execution pass; the old script and developer tools are absent; worker startup from `/` with malformed stdin exits 10 with no output and no broker access.

#### Scenario: Authentication and timezone guards

- **WHEN** `.venv/bin/python -m pytest -q tests/test_ghostfolio_auth.py tests/test_foundation_runtime.py` runs with synthetic ENV and HTTP
- **THEN** one credential is mandatory, Security Token exchange occurs once, failed authentication stops reads, origins and redirects stay bounded, and invalid TZ permits no financial write.

Baseline: README, `entrypoint.sh`, `tests/test_notify.py` and `tests/test_ghostfolio_auth.py` at `7751e02f90c73b0e44e67f052c715226af436aa8`. Installed-module execution, Python 3.14 and forced timezone simulation are changes to that baseline.

### Requirement: Cash check and simulation

Current EUR cash MUST come from DEGIRO, match the statement and never be rebuilt from old balances. A one-cent difference SHALL be accepted only when its execution amount confirms it; any other difference MUST stop writes. DRY_RUN SHALL authenticate, read, log proposals and the cash change, write nothing and not advance coverage.

Simulation values SHALL be trimmed and case-insensitive. Absent or blank DRY_RUN SHALL emit `DRY_RUN not set: simulation, nothing written` once per invocation, including configuration failure. Invalid DRY_RUN SHALL fail before broker/Ghostfolio HTTP. Each failed invocation SHALL attempt exactly one sanitized failure notification when configured, in manual and scheduled simulation or live mode. This grants no financial access. Successful simulation SHALL remain silent. Delivery failure SHALL preserve the original exit status.

Exception: explicit live mode forced into simulation by missing/invalid TZ SHALL send one configured summary naming that reason, even on success. A failure SHALL take precedence and use one failure summary, never a second dispatch. No new token-expiry reminder mechanism is required.

Ghostfolio account list/detail reads SHALL use a 120-second inactivity timeout; cash PUT SHALL retain 30 seconds. Authentication SHALL retain connect/read timeouts of 10/30 seconds. Existing origin checks, disabled ambient proxies, redirect refusal and secret-free diagnostics SHALL remain.

#### Scenario: Cash and failure contracts

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_notify.py tests/test_foundation_runtime.py tests/test_ghostfolio_auth.py` runs
- **THEN** currency, freshness and exact cash guards pass; the existing corroborated execution-cent rule remains bounded; simulation sends no financial writes; blank/default/invalid modes and failed delivery follow the notification contract; account reads use 120 seconds and cash writes use 30 seconds.

#### Scenario: Rounding in simulation

- **WHEN** `docker compose up` runs with `DRY_RUN=1` and an execution has a one-cent rounding
- **THEN** logs show `Cash statement verified with 1 corroborated one-cent execution rounding differences` and `(no update sent)`.

Baseline: `tests/test_degiro_cash.py`, `tests/test_notify.py`, `docs/ghostfolio-auth.md`. Manual simulation failures were previously silent; that notification behavior deliberately changes.

### Requirement: Additive import and recovery

Imports SHALL keep existing activities, skip known duplicates and record write intent first. Rolling matching with manual activities SHALL not certify history. After a lost reply, an exact readback MUST confirm the import; until then, writes and cash updates stay blocked.

A valid 2xx import response SHALL identify unique created rows and prove account, comment, timestamp, type, quantity, price, fee, currency and returned profile. Only proven accepted buys SHALL authorize subsequent sells. A known short response SHALL retain proven creations, identify omissions in private diagnostics, fail the account and never retry automatically. An unknown response SHALL retain uncertainty and the durable pending intent. Both cases SHALL block cash until DEGIRO's existing completion conditions are met.

A new MANUAL profile symbol returned as UUID SHALL be associated with its requested profile only through exact identity, financial readback and profile evidence. Amount equality or a name alone SHALL NOT establish ownership. Subsequent reads SHALL preserve that association and deduplicate fees/interest. Unknown or conflicting mappings SHALL stop financial writes.

#### Scenario: Complete, short and uncertain acceptance

- **WHEN** `.venv/bin/python -m pytest -q tests/test_ghostfolio_core.py tests/test_degiro_sync.py tests/test_degiro_recovery.py tests/test_foundation_acceptance.py` runs
- **THEN** exact accepted subsets remain explicit; omitted buys cannot back sells; no partial or uncertain batch is replayed; cash stays fenced; restart and selected positive recovery preserve the journal contract.

#### Scenario: Repeated or interrupted import

- **WHEN** an accepted import repeats or its reply is lost
- **THEN** no duplicate is created; an incomplete readback blocks further writes.

#### Scenario: MANUAL profile rewrite

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_acceptance.py -k manual_profile` runs synthetic UUID rewrite, repeated-read and conflicting-profile cases
- **THEN** proven fee/interest rows remain owned and deduplicated, while ambiguous or financially changed readback blocks the account.

Baseline: `tests/test_rolling.py`, `tests/test_degiro_recovery.py` and `docs/recovery.md`. UUID association and the reviewed v3.0.0 core are additions; this does not claim target-version lab acceptance.

## ADDED Requirements

### Requirement: Separate read, selection and confirmation contracts

The Ghostfolio adapter SHALL fetch existing activities once per established execution phase. Pure indexing SHALL validate completeness, masking, ownership, profiles and exact numeric evidence without HTTP or writes. The synchronization module SHALL select and validate imports from those indexes and broker inputs without dispatching them. It SHALL preserve DEGIRO's whole-account gate, event classification and sell coverage.

Accepted-result recording SHALL receive only rows proven accepted by response or exact recovery readback. It SHALL update only the matching source identities and holdings. Pending or omitted rows SHALL NOT enter confirmed state. Simulation SHALL update only disposable proposal state and SHALL NOT certify journal coverage. Durable intent SHALL precede dispatch. Diagnostics SHALL observe pre-deduplication inputs without mutating selection.

These contracts adapt IBKR v3.0.0 `ghost_get_existing_orders`, `index_existing_activities`, `select_account_activities` and `record_accepted_activities`. DEGIRO SHALL retain its own exact decimal indexes, broker identity grammar and durable journal semantics.

#### Scenario: Selection and confirmed state remain independent

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_selection.py tests/test_degiro_recovery.py tests/test_rolling.py` runs complete, masked, duplicate, rejected, simulated and partially accepted batches
- **THEN** pure indexing and selection perform no HTTP, incomplete input blocks dispatch, only confirmed rows update durable ownership and holdings, and simulated or omitted buys cannot authorize a real sell.

### Requirement: Versioned DEGIRO ownership

The common identity grammar SHALL be `<BROKER>#v<N>#<source-account>:<KIND>:<source-id>`. The first versioned DEGIRO writer SHALL use generation 1. Account/source segments SHALL match `[A-Za-z0-9._-]+`; retain DEGIRO's existing stronger numeric-ID validation. Writer comments SHALL contain at most 2000 ASCII characters. TRADE SHALL map only to BUY/SELL; DIVIDEND, FEE, INTEREST and COMPENSATION SHALL retain their existing event-kind distinctions and source-row IDs. No trimming, hashing, truncation, calendar grouping or inferred identity is allowed.

Writer qualification SHALL establish account scope, source-row ID stability across overlapping windows, relevant event-kind uniqueness and exact destination comment/readback preservation on the qualified image. Keep the evidence and any limits in the existing source contract and operation record. Offline fixtures or a single observed window SHALL NOT establish broker lifetime uniqueness. Unresolved identity ambiguity SHALL block writer qualification.

Readers SHALL accept current unversioned DEGIRO comments and generation 1. Malformed or unknown reserved `DEGIRO#v` identities SHALL block before financial writes. Legacy and versioned forms of one event SHALL resolve to the same source ownership. Exact unchanged legacy ownership SHALL suppress reimport. Conflicting values or duplicate claims SHALL block; proximity or equal amounts SHALL NOT resolve ownership. Newly accepted rows SHALL update only their proper activity/holding state.

No stored comment SHALL be rewritten by sync. After generation-1 rows exist, rollback SHALL use a qualified dual reader; older binaries are not a safe rollback. Historical conversion remains a separate future operation.

#### Scenario: Dual-reader and source scope

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_identity.py tests/test_rolling.py` runs equal IDs in different source accounts, both generations, mixed rows, unknown versions and changed payloads
- **THEN** independent source accounts stay distinct, unchanged legacy rows produce no duplicate, malformed/ambiguous ownership blocks, accepted buys alone affect holdings, and no historical row is changed.

### Requirement: Exact read-only reconciliation

DRY_RUN SHALL compare source events with owned destination activities before import deduplication. It SHALL retain exact original numeric evidence, normalize only proven supported currency units and distinguish coherent, informational, noise, to-check, uncertain and outside-window findings. Every in-scope source event and destination activity SHALL be accounted for once; ownership contention SHALL remain uncertain. Missing security, currency, date or quantity proof SHALL remain unavailable. Dividend activity quantity 1 SHALL NOT be presented as proven security quantity.

The report SHALL show expected/observed identity and financial checks, one Action line per block and an explicit statement that nothing was written. Display rounding SHALL use currency minor units without changing comparison. No Python representations or exponent notation SHALL appear. Candidate proposals SHALL identify the compared activity; weak matches SHALL not claim a row to keep. Quantity has zero tolerance. No generic amount threshold or IBKR-only declared-rate cause SHALL be imported into DEGIRO. Any accepted difference SHALL name its existing proven DEGIRO cause.

Reporting SHALL reuse the existing reads without writes, extra broker/Ghostfolio reads or input replacement. Findings SHALL not change selection, exits or notifications. Technical failures retain their failure contract. Live sync SHALL not run the historical report.

#### Scenario: Exact and readable findings

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_diagnostics.py tests/test_simulation_review.py` runs exact decimals, ambiguous ownership, split rows, wrong action targets, unsupported currencies, quantity differences and outside-window history
- **THEN** deterministic findings conserve coverage, retain uncertainty and exact comparison, use plain display, and leave import payloads, HTTP counts, exits and notifications unchanged.

### Requirement: Native acceptance evidence

At DEBUG, the connector SHALL emit single-line `LAB_EVIDENCE ` followed by compact finite JSON with exactly `kind` and `value`. Emit `window` from the proven DEGIRO interval, `preview` from each complete simulated batch including empty batches, and `cash` from the validated target. Cash evidence is a target, not proof of a write. INFO SHALL gain no machine-evidence lines. Evidence SHALL exclude credentials, ENV, headers, raw responses and URLs. Missing or nonfinite evidence SHALL not change financial operations; incomplete evidence SHALL fail lab qualification.

#### Scenario: Native evidence without extra access

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_evidence.py tests/test_simulation_review.py` runs synthetic window/preview/cash cases
- **THEN** every DEBUG record parses on one line with exact payload fields and finite values, INFO has no evidence records, secrets stay absent, and request/financial results remain unchanged.
