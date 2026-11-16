# degiro-synchronization Specification

## Purpose
Describe how the connector copies one DEGIRO account into one existing Ghostfolio account today, and when it refuses.

## Requirements

### Requirement: Supported deployment

The supported deployment SHALL be `compose.yaml`: settings from ENV, DEGIRO login only from one Bitwarden/Vaultwarden item, exactly one Ghostfolio credential, `SYNC_MODE=rolling`, 90 days, `TZ=Europe/Zurich`. `DRY_RUN` absent, blank or `1`/`true`/`yes`/`on` SHALL simulate; `0`/`false`/`no`/`off` SHALL write; another value SHALL stop before broker access. Empty `CRON` SHALL run once; a `CRON` that is not five numeric fields SHALL stop before the connector starts. `APPRISE_URLS` SHALL send failure alerts without secrets.

The image and CI SHALL use Python 3.14 after the pinned runtime dependency set passes import, offline application and native container checks on both supported architectures. Align all Python workflow pins and Renovate ranges. The image SHALL install the connector package and run `python -m ghostfolio_degiro_sync`. Every intermediate extraction SHALL remain runnable in Docker; package installation, build-context inclusion and resources precede imports into the old command. Entrypoint options SHALL retain their meaning. CRON SHALL invoke the installed module with `--sync`. Remove the old script path only at final cutover. Preserve ENV names, supported modes, exit meanings, snapshot formats and recovery commands.

The notification worker SHALL use isolated module execution, bounded lifetime, restricted ENV and stdin payloads. Worker mode SHALL never synchronize or load broker credentials. Developer tools SHALL stay outside the image. Missing or invalid IANA TZ SHALL force simulation before financial dispatch and emit one fixed warning. This is a common runtime safety contract for local-day diagnostics, not a claim that DEGIRO needs Flex suffix parsing. Preserve the existing Europe/Zurich broker window and explicit offset validation. README SHALL declare the changed TZ prerequisite as BREAKING.

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

### Requirement: Rolling mode

Rolling SHALL read the 90 days that end today in Europe/Zurich, including events before the first run, and propose only activities missing in Ghostfolio. After a long outage, an explicit earlier catch-up SHALL cover the recorded gap; an uncovered gap SHALL stop the run. Positions and the DEGIRO statement MUST agree. Older history and cost basis stay unverified.

#### Scenario: Read-only run

- **WHEN** `docker compose up` runs with `DRY_RUN=1`
- **THEN** logs show `Sync DRY_RUN: <n> proposed activities, 0 accepted` and `Rolling 90-day contract verified; historical completeness and basis remain unverified`.

Proof: retained real DRY_RUN through `--sync`, not Compose, 2026-10-10 (log wording before commit c795f24): 2 proposed, 0 accepted, Ghostfolio unchanged, coverage not advanced. Offline: `.venv/bin/python -m pytest -q tests/test_rolling.py` reports passed, including first-run and catch-up tests.

### Requirement: Prospective mode

Prospective SHALL start from a fixed opening snapshot bound to the account, whose positions match DEGIRO. It SHALL keep older Ghostfolio history, re-read from the opening date to today and propose only later events. Cost basis stays unverified. Compose does not offer this mode.

#### Scenario: Changed opening snapshot

- **WHEN** the opening snapshot or later history does not agree
- **THEN** the run stops; when they agree, later events are proposed.

Proof: `.venv/bin/python -m pytest -q tests/test_prospective.py` reports passed.

### Requirement: Full-history limitation

`full_history` SHALL read the requested period. Without proven completeness, DRY_RUN SHALL say so and a live run SHALL refuse writes. Choosing it does not prove that DEGIRO returns all history. Compose does not offer this mode.

#### Scenario: Unproven completeness

- **WHEN** completeness is unproven
- **THEN** DRY_RUN reports it; a live run exits non-zero without writes.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_sync.py -k 'whole_account or unverified_history or full_history'` reports passed.

### Requirement: Supported accounting

The connector SHALL produce BUY/SELL; gross DIVIDEND with its one matching tax as fee; FEE for an exchange connection charge; INTEREST of zero for EUR Flatex interest; separate INTEREST for positive EUR fund compensation. Brokerage and currency conversion cost SHALL go into the execution fee. Currency exchange, withdrawals, cash sweeps and execution cash rows SHALL create no activity. Announced dividends SHALL be ignored. Instruments MUST remain STOCK with contract size 1.

BUY/SELL and paid dividends SHALL support compatible currencies and quote units under Currency evidence and units. This currency extension SHALL NOT change the EUR standalone-fee or cash-yield conventions, tax pairing, stable identities or unknown-category guards. New currencies SHALL NOT activate new instrument classes or income categories.

#### Scenario: Supported events

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_trades.py tests/test_degiro_dividends.py tests/test_degiro_fees.py tests/test_degiro_cash_yield.py` runs existing and additional verified currency cases
- **THEN** amounts, units and identities are preserved, with no duplicate fees, inferred tax or unqualified income policy.

Baseline: the same test files and `docs/source-contract.md` cover the current event classes. Only the fixed trade/dividend currency restriction changes.

### Requirement: Selected-account refusal

Unknown, unsupported or ambiguous evidence relevant to the selected operation MUST stop all writes for the selected account. Relevance SHALL include candidate construction, position quantities, manual matching, broker ownership, protected history and pending-result recovery. A date before the selected source interval alone SHALL NOT make evidence irrelevant. This includes manual-match date ranges that overlap that interval.

Structurally valid historical activities SHALL remain in complete read evidence. Unavailable monetary units SHALL NOT block only when the connector proves those units do not affect any required control. Such history SHALL remain unverified. Position controls SHALL still require exact quantities and security identity. Broker-owned activities SHALL retain exact identity and financial checks. The connector SHALL NOT suppress, rewrite, delete or silently certify a historical row to pass admission.

A tax without exactly one matching dividend, wrong units used in an operation or changed ownership MUST block the account. Malformed, masked, duplicated, inactive or future selected-account context SHALL retain its existing refusal rules. Old fund history and corporate actions SHALL remain unsupported when relevant.

A golden snapshot MAY contain incomplete or unsupported activities belonging to other accounts. The connector SHALL preserve those rows for evidence and SHALL NOT let them block the selected account.

#### Scenario: Unsupported selected-account evidence

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_sync.py tests/test_rolling.py tests/test_foundation_acceptance.py` runs relevant unknown units, ambiguous dividend tax, changed ownership, masked context and pending recovery
- **THEN** synchronization refuses before financial writes and preserves the existing uncertainty fences.

#### Scenario: Historical currencies without a special-case exception

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_acceptance.py tests/test_rolling.py` runs old unowned dividends and holdings in several currencies, unknown historical monetary units and rows near the manual-match boundary
- **THEN** valid compatible currencies are admitted, irrelevant unavailable monetary evidence remains explicitly unverified, relevant unavailable evidence blocks, and no activity is dropped or changed.

#### Scenario: Unrelated golden history

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_sync.py` runs unsupported rows on another account with valid selected-account evidence
- **THEN** those rows remain in the readback evidence and the selected account continues through reconciliation.

Baseline changed: `tests/test_foundation_acceptance.py` currently preserves unsupported inherited holding units but not inherited dividend units. `tests/test_degiro_sync.py` and `tests/test_rolling.py` own selected-account and complete-context refusal.

### Requirement: Cash check and simulation

Current cash MUST come from fresh DEGIRO evidence and never from old ledger balances. The connector SHALL keep one configured Ghostfolio account in EUR. It SHALL consume the verified DEGIRO-reported EUR total through the existing qualified layout. Its current source-account binding, freshness, complete component coverage and exact agreeing cash aliases SHALL remain required. Foreign cash components and pending settlement MUST be zero. Positive, zero and negative verified EUR totals SHALL be accepted.

Nonzero foreign cash, other base currencies and unqualified layouts SHALL block before any financial write. This release SHALL NOT claim their aggregate semantics are qualified. A valid currency code, a list of currency balances or a foreign-currency security SHALL NOT authorize a foreign-cash aggregate. Missing, duplicate, contradictory or stale evidence SHALL retain refusal. No local FX calculation, unlike-currency sum, account creation or account-currency change is permitted.

Nonzero foreign-cash aggregate support is deferred by the operator's 2026-11-16 scope decision. A later approved change must prove field meaning, base denomination, full coverage and independent equality before that support can be enabled. The connector SHALL NOT create nonzero foreign balances to obtain this evidence.

A one-cent statement difference SHALL remain accepted only under its existing corroborated execution rule. This change SHALL NOT extend that tolerance to other categories or monetary scales. DRY_RUN SHALL authenticate, read, log proposals and the cash change, write nothing and not advance coverage.

Simulation values SHALL be trimmed and case-insensitive. Absent or blank DRY_RUN SHALL emit `DRY_RUN not set: simulation, nothing written` once per invocation, including configuration failure. Invalid DRY_RUN SHALL fail before broker/Ghostfolio HTTP. Each failed invocation SHALL attempt exactly one sanitized failure notification when configured, in manual and scheduled simulation or live mode. This grants no financial access. Successful simulation SHALL remain silent. Delivery failure SHALL preserve the original exit status.

Exception: explicit live mode forced into simulation by missing/invalid TZ SHALL send one configured summary naming that reason, even on success. A failure SHALL take precedence and use one failure summary, never a second dispatch. No new token-expiry reminder mechanism is required.

Ghostfolio account list/detail reads SHALL use a 120-second inactivity timeout; cash PUT SHALL retain 30 seconds. Authentication SHALL retain connect/read timeouts of 10/30 seconds. Existing origin checks, disabled ambient proxies, redirect refusal and secret-free diagnostics SHALL remain.

#### Scenario: Cash and failure contracts

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_notify.py tests/test_foundation_runtime.py tests/test_ghostfolio_auth.py` runs existing EUR cases and positive, zero and negative verified EUR totals
- **THEN** currency, freshness, coverage and exact cash guards pass; simulation sends no financial writes; invalid inputs and failed delivery preserve the notification contract; account reads use 120 seconds and cash writes use 30 seconds.

#### Scenario: One EUR account with foreign-cash refusal

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_rolling.py` runs positive, zero and negative verified EUR totals, nonzero foreign components, duplicate aliases, missing base denomination and unqualified layouts
- **THEN** only the verified EUR total is proposed for the existing account; foreign cash and uncertain cases refuse before imports or cash writes, without a local FX calculation or account creation.

#### Scenario: Rounding in simulation

- **WHEN** `docker compose up` runs under authorized DRY_RUN against a qualified snapshot with one supported execution-cent rounding difference
- **THEN** logs show `Cash statement verified with 1 corroborated one-cent execution rounding differences` and `(no update sent)`.

Baseline changed: `tests/test_degiro_cash.py` permits only EUR, zero foreign components and exact agreeing EUR aliases. `docs/source-contract.md` records that observed configuration. Nonzero multicurrency aggregates are outside this release and remain refused. Their source qualification belongs to a later approved change. Notification and transport baselines remain `tests/test_notify.py` and `docs/ghostfolio-auth.md`.

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

### Requirement: Separate read, selection and confirmation contracts

Normal sync SHALL fetch one complete existing-activity snapshot before selection; existing exact post-write/recovery readbacks remain separate phases. Diagnostics SHALL add no reads. Pure indexing SHALL validate completeness, masking, ownership, profiles and exact numeric evidence without HTTP or writes. Selection SHALL use an injected clock and produce typed results containing proposals, rejected/deferred outcomes and holdings evidence, without dispatch. Preserve DEGIRO's whole-account gate, classification and sell coverage. Journal operations SHALL be functions over typed records, not stateful business classes.

Accepted-result recording SHALL receive only rows proven accepted by response or exact recovery readback. It SHALL update only the matching source identities and holdings. Pending or omitted rows SHALL NOT enter confirmed state. Simulation SHALL update only disposable proposal state and SHALL NOT certify journal coverage. Durable intent SHALL precede dispatch. Diagnostics SHALL observe pre-deduplication inputs without mutating selection.

These contracts adapt IBKR v3.0.0 `ghost_get_existing_orders`, `index_existing_activities`, `select_account_activities` and `record_accepted_activities`. DEGIRO SHALL retain its own exact decimal indexes, broker identity grammar and durable journal semantics.

#### Scenario: Selection and confirmed state remain independent

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_selection.py tests/test_degiro_recovery.py tests/test_rolling.py` runs complete, masked, duplicate, rejected, simulated and partially accepted batches
- **THEN** pure indexing and selection perform no HTTP, incomplete input blocks dispatch, only confirmed rows update durable ownership and holdings, and simulated or omitted buys cannot authorize a real sell.

### Requirement: Versioned DEGIRO ownership

The common identity grammar SHALL be `<BROKER>#v<N>#<source-account>:<KIND>:<source-id>`. The first versioned DEGIRO writer SHALL use generation 1. Account/source segments SHALL match `[A-Za-z0-9._-]+`; retain DEGIRO's stronger numeric-ID validation. Comments SHALL contain at most 2000 ASCII characters. Map TRADE to BUY/SELL, DIVIDEND to DIVIDEND, FEE to FEE, and INTEREST/COMPENSATION to INTEREST while retaining their distinct source kinds. Preserve exact source-row IDs. No trimming, hashing, truncation, calendar grouping or inferred identity is allowed.

Writer qualification SHALL establish account scope, source-row ID stability across overlapping windows, relevant event-kind uniqueness and exact destination comment/readback preservation on the qualified image. Keep the evidence and any limits in the existing source contract and operation record. Offline fixtures or a single observed window SHALL NOT establish broker lifetime uniqueness. Unresolved identity ambiguity SHALL block writer qualification.

Readers SHALL accept current unversioned DEGIRO comments and generation 1. Malformed or unknown reserved `DEGIRO#v` identities SHALL block before financial writes. Legacy and versioned forms of one event SHALL resolve to the same source ownership. Exact unchanged legacy ownership SHALL suppress reimport. Conflicting values or duplicate claims SHALL block; proximity or equal amounts SHALL NOT resolve ownership. Newly accepted rows SHALL update only their proper activity/holding state.

Index reserved DEGIRO identities across the complete destination snapshot by source account/kind/ID, before selecting the destination account. A known event in an old destination account SHALL NOT become a new import after target remapping. Report the conflict without moving a row or borrowing its holdings. Inactive/excluded rows still occupy identities but SHALL NOT authorize sales.

Normal sync SHALL never rewrite stored comments. The explicit historical conversion below ships with the dual reader and writer in this delivery; no prior reader-only release is required. After generation-1 rows exist, use the exact qualified candidate forced to simulation as the safe-halt floor. This stops financial writes; it does not undo data or guarantee fallback to an older executable. If the candidate cannot start, keep writers stopped until a compatible repair is qualified. An old binary is not a safe fallback merely because source commits can be reverted.

#### Scenario: Dual-reader and source scope

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_identity.py tests/test_rolling.py` runs different source accounts, both generations, destination remapping, unknown versions, changed payloads and forced simulation with mixed history
- **THEN** independent source accounts stay distinct, remapping cannot expose duplicates, conflicting ownership blocks, accepted buys alone affect holdings, normal sync changes no historical row, and the qualified candidate in simulation sends no financial writes.

### Requirement: Complete historical identity inventory and offline preview

The maintenance preview SHALL inventory every existing DEGIRO-owned activity in the complete target snapshot, including history older than rolling 90 days and inactive/excluded rows. It SHALL not claim that DEGIRO can return all past events. Use exact saved source evidence, mappings, existing ownership and durable records where qualified. Record missing source coverage explicitly. Classify each row exactly once as eligible, already versioned, manual/other broker, unsupported, unproven, ambiguous or conflicting. Preserve every ineligible row and report its reason. Do not invent identity from amounts, dates or symbols alone, accept id0 as stable, or convert another broker's/manual activity.

Only a unique proven legacy-to-v1 association with unchanged financial context SHALL be eligible. The proposed new comment SHALL be unoccupied elsewhere. Already occupied, duplicate or changed ownership blocks affected conversions. All proposed replacements SHALL preserve Ghostfolio activity IDs, source account/kind/ID, dates, type, exact quantity/price/fee/currency, tags, account and profile identity. The user-visible change is only the connector identity stored in `comment`.

Preview SHALL run offline without credentials or network, regardless of inherited DRY_RUN. It SHALL preserve input bytes and write only a new private output directory. Publish a deterministic keyed YAML manifest with rows keyed by activity ID, old/new comments, eligibility/reasons, exact fingerprints, complete inventory counts, input/mapping/tool hashes, declared source windows, scope and destination image/version. Keep volatile timestamps outside the hashed decisions. Reject input/output overlap, duplicate YAML keys, incomplete or redacted evidence. Do not duplicate canonical configuration into hand-edited prose.

Replay the complete import selection against original and proposed snapshots with the same fixed clock, source windows and mapping. Payloads, duplicate decisions, holdings and failure outcomes SHALL remain identical, not just counts. Missing proof SHALL remove affected replacements; no account remapping or previously suppressed event may become a new import. Unconverted rows remain readable by the dual reader. They SHALL NOT bypass normal whole-account guards.

#### Scenario: All-history preview without mutation

- **WHEN** `.venv/bin/python -m pytest -q tests/test_identity_migration.py -k preview` runs old history, incomplete windows, exact/mismatched source evidence, zero-value MANUAL events, duplicate claims, remapped targets and before/after selection replay
- **THEN** every row has one decision, only unique proven comments are eligible, every input remains byte-identical, no network or credential is used, output is deterministic, and changed selection blocks the affected conversion.

Baseline: current `docs/source-contract.md`, canonical legacy comments, saved fixture schemas and `docs/recovery.md`; all-history inventory does not establish complete broker history. The migration engine adapts IBKR v3.0.0's explicit maintenance mechanism, not its Flex associations or Yahoo-only update restriction.

### Requirement: Guarded historical identity conversion

The versioned maintenance command SHALL convert eligible historical identities in the same delivery as the new writer. It SHALL be separate from scheduled sync and from DRY_RUN=false. Preview approval does not authorize real writes. An operation plan validated once SHALL bind exact executable commands, manifest hash, owner/account scope, destination image/version, backup, writer exclusion, unsettled-request checks, expected write count, measured pacing, stop rules and recovery. Prepare this operation during the delivery; do not require a separate reader-only release or waiting period.

Maintenance SHALL accept semantic Ghostfolio versions at or above 3.86.0 without an exact-version or hard-coded upstream source commit requirement. A prerelease of the minimum version is below the floor; build metadata does not change precedence. Invalid or older versions SHALL fail before authentication or writes. Each operation SHALL still bind its observed destination version and image to the reviewed snapshot and approval. Newer-version eligibility SHALL preserve the existing authorization, per-class qualification, ownership, financial preservation, pending-request, settlement and reversal requirements.

Before the first write, stop competing writers, verify a recoverable backup and re-read complete unredacted destination state. Reject stale fingerprints, changed mappings/image, occupied identities or scope drift. Use existing private authentication and bounded transport with a dedicated maintenance allowlist for `PUT /api/v1/activities/{id}`. The normal sync transport SHALL NOT gain permission to modify historical activities.

Qualify the exact target UpdateOrderDto and update effects from its pinned implementation and the lab before enabling conversion. An API request may require financial fields even though only the comment may change. Construct an explicit allowlist; never echo a GET object. Preserve exact numeric transport, activity currency, tags, account and profile identity. Prove MANUAL fee/interest/compensation, valid zero values and returned UUID profiles, not just Yahoo BUY/SELL/DIVIDEND. If any activity class cannot be preserved, mark it unqualified and leave its rows intact. Background/profile effects or unproven pacing block that class; no financial correction, insert, delete, cash or platform write is permitted.

Persist each original row fingerprint, comment and bounded request as pending in a locked private YAML journal before dispatch. Prove exact post-write readback and unchanged protected rows before advancing. Stop on failed/uncertain HTTP, normalization, partial completion or changed context. Retain pending state and confirmed subsets; never retry automatically. An unchanged/old readback alone does not prove that a delayed request cannot complete. Independent completion/cancellation evidence is required before retry or reversal; otherwise keep the operation stopped.

The API MAY omit `isDraft`; maintenance SHALL still enforce draft and exclusion tags. An owned comment PUT MAY advance only its row's backend-managed Order `updatedAt` monotonically. Maintenance SHALL retain the complete observed postimage, including that timestamp, for conversion and reversal. It SHALL NOT send timestamps in the update DTO or relax checks on other fields or protected rows.

#### Scenario: Conversion and uncertain completion

- **WHEN** `.venv/bin/python -m pytest -q tests/test_identity_migration.py -k apply` exercises exact qualified DTOs, MANUAL/zero values, stale manifests, concurrent writers, decimal loss, profile effects, partial success, delayed writes and timeouts
- **THEN** only approved comments change, every other stored field is preserved, journal intent precedes each request, exact readback verifies confirmed rows, and every uncertain result stops without retry.

#### Scenario: Newer Ghostfolio maintenance

- **WHEN** conversion and reversal use a newer semantic destination version with complete matching operation evidence
- **THEN** version eligibility permits both operations without an old source commit, while invalid or older versions and changed approved destinations fail before authentication or writes.

### Requirement: Historical conversion inspection and reversal

Inspection SHALL use saved snapshots and the journal without network or writes. It SHALL report original, converted, changed and uncertain rows, distinguishing request settlement from observed state. Reversal SHALL use the same engine and independent request-settlement evidence under the approved operation's exact recovery scope. Restore only original comments of journal-owned converted rows whose full financial/ownership context remains unchanged. Drift SHALL block the affected reversal.

Record reversal intent before each request and prove exact readback. Never reverse new imports, delete rows or restore an entire database automatically. Retain every newly imported v1 activity. Before resuming sync, prove the exact mixed-history preview, unchanged source selection and zero duplicates. Comment reversal alone does not qualify old code when any new v1 row remains. A source Git revert is applicable only before versioned data exists, or after separately proving that the selected binary reads all retained data. No global database restore is the default recovery.

#### Scenario: Mixed-history inspection and reversal

- **WHEN** `.venv/bin/python -m pytest -q tests/test_identity_migration.py -k 'inspect or rollback'` runs confirmed/uncertain conversions, delayed requests, manual edits, newly imported v1 rows and reversal interruption
- **THEN** offline inspection changes nothing, only unchanged journal-owned comments can be restored after settlement, new rows remain, reversal is journaled, and unsafe old-binary restart remains blocked.

### Requirement: Exact read-only reconciliation

DRY_RUN SHALL compare source events with owned destination activities before import deduplication. It SHALL retain exact original numeric evidence, normalize only proven supported currency units and distinguish coherent, informational, noise, to-check, uncertain and outside-window findings. Every in-scope source event and destination activity SHALL be accounted for once; ownership contention SHALL remain uncertain. Missing security, currency, date or quantity proof SHALL remain unavailable. Dividend activity quantity 1 SHALL NOT be presented as proven security quantity.

The report SHALL show expected/observed identity and financial checks, one Action line per block and an explicit statement that nothing was written. Display rounding SHALL use proved currency minor units without changing comparison. No Python representations or exponent notation SHALL appear. Candidate proposals SHALL identify the compared activity; weak matches SHALL not claim a row to keep. Quantity has zero tolerance. No generic amount threshold or IBKR-only declared-rate cause SHALL be imported into DEGIRO. Any accepted difference SHALL name its existing proven DEGIRO cause.

The report SHALL distinguish a raw currency, a currency resolved from the same activity profile and an unavailable unit. It SHALL explain historical evidence that does not affect selection without marking it financially verified. For cash, it SHALL identify the broker base currency and reported aggregate separately from original currency components. It SHALL NOT display a hypothetical sum as available cash or claim that missing broker evidence has been qualified.

Reporting SHALL reuse the existing reads without writes, extra broker/Ghostfolio reads or input replacement. Findings SHALL not change selection, exits or notifications. Technical failures retain their failure contract. Live sync SHALL not run the historical report.

#### Scenario: Exact and readable findings

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_diagnostics.py tests/test_simulation_review.py` runs exact decimals, ambiguous ownership, split rows, wrong action targets, new currencies, quantity differences and outside-window history
- **THEN** deterministic findings conserve coverage, retain uncertainty and exact comparison, use plain display with currency provenance, and leave import payloads, HTTP counts, exits and notifications unchanged.

Baseline: the same tests and `ghostfolio_degiro_sync/diagnostics.py` already preserve raw numbers and observational reports. This change extends unit coverage and cash explanation.

### Requirement: Native acceptance evidence

At DEBUG, the connector SHALL emit single-line `LAB_EVIDENCE ` followed by compact finite JSON with exactly `kind` and `value`. Emit `window` from the proven DEGIRO interval, `preview` from each complete simulated batch including empty batches, and `cash` from the validated target. Cash evidence is a target, not proof of a write. INFO SHALL gain no machine-evidence lines. Evidence SHALL exclude credentials, ENV, headers, raw responses and URLs. Missing or nonfinite evidence SHALL not change financial operations; incomplete evidence SHALL fail lab qualification.

Implement ENV `LOG_LEVEL` with default INFO and explicit DEBUG support. Invalid values SHALL fail configuration before network access. Configure the connector logger only; do not turn on third-party HTTP/broker loggers or bypass existing redaction boundaries. Emit native records once through the adapter while core logs remain suppressed. README SHALL explain DEBUG and its private-output boundary.

#### Scenario: Native evidence without extra access

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_evidence.py tests/test_simulation_review.py` runs synthetic window/preview/cash cases
- **THEN** every DEBUG record parses on one line with exact payload fields and finite values, INFO has no evidence records, secrets stay absent, and request/financial results remain unchanged.

### Requirement: Consistent runtime software identity

New release images SHALL report `ghostfolio-degiro-sync version X.Y.Z — commit <prefix>` at connector container startup and at every normal application invocation. The prefix SHALL be the first twelve lowercase hexadecimal characters of the embedded full commit. One-off, explicit connector options and CRON cycles SHALL report the same identity before configuration failure or broker access. Local builds without metadata SHALL use `dev` and `unknown`.

The isolated notification worker SHALL remain silent and SHALL NOT emit startup identity. An explicit arbitrary command passed to the Docker entrypoint SHALL keep its current command and exit behavior. Identity reporting SHALL use no network lookup, Docker socket or operator version setting. Existing logging streams, severity, failure notification count, scheduler behavior and exit status SHALL remain unchanged.

Baseline changed: `entrypoint.sh` currently emits APP_VERSION only on its default path; `app.main` has no software-identity line. Existing regressions are in `tests/test_foundation_runtime.py`, `tests/test_notify.py` and `tests/test_failure_diagnostics.py`.

#### Scenario: Identity across execution modes

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_runtime.py tests/test_notify.py tests/test_failure_diagnostics.py` runs synthetic release and local startup cases
- **THEN** one-off, explicit connector options and scheduled application cycles show the same version and commit prefix, missing configuration still shows identity, the notification worker stays silent, and exit/notification contracts pass.

### Requirement: Fixed Docker startup banner

The Docker entrypoint SHALL print a fixed ASCII `DEGIRO SYNC` banner and a `DEGIRO -> Ghostfolio` subtitle once per connector container start. The dynamic identity SHALL follow the banner. Default one-off, CRON and explicit connector-option startup SHALL show the banner. Individual scheduled cycles SHALL print identity without repeating the banner.

The banner SHALL require no new setting, runtime renderer, terminal escape code or external request. Arbitrary command execution SHALL keep its current behavior.

Baseline changed: `entrypoint.sh` has no banner. The sibling entrypoint provides a static literal; its broker name SHALL be adapted.

#### Scenario: Banner in installed startup

- **WHEN** `.venv/bin/python scripts/smoke_container.py "$IMAGE"` runs against the isolated candidate image
- **THEN** connector startup shows one banner followed by the identity in one-off and scheduled modes, scheduled cycles do not repeat the banner, and the existing fail-closed smoke passes without credentials or network.

### Requirement: Currency evidence and units

The connector SHALL distinguish a currency accepted for reading from a currency whose monetary units are proved for an operation. It SHALL use versioned authoritative currency reference data and the qualified Ghostfolio currency contract. A code with no proved monetary unit SHALL NOT receive a default of two decimal places. A syntactically valid code alone SHALL NOT authorize arithmetic or dispatch.

The connector SHALL preserve raw currency fields and their origin. A present null activity currency SHALL resolve only from the valid profile carried by that same activity. A missing field, an invalid current profile or an unrelated activity SHALL NOT supply currency evidence. Explicit activity currency SHALL remain explicit. Effective currency SHALL be used consistently for selection, acceptance, recovery and reporting without changing captured bytes.

For supported STOCK operations, compatible currencies SHALL NOT be restricted to EUR, USD and JPY. Each operation SHALL prove broker currency, quote currency, any exact unit factor and the destination representation. Derived quote units such as GBp SHALL remain distinct from GBP. A conversion SHALL scale monetary values exactly once, preserve quantity and conserve value in a common unit. Ticker suffixes or numerical proximity SHALL NOT establish a factor. Quantity SHALL retain zero tolerance. Currency reference precision SHALL NOT create a new amount tolerance or round source prices.

Baseline changed: `README.md` limits quotes to EUR/USD/JPY. `tests/test_foundation_acceptance.py` resolves supported profile currencies but permits only quantity evidence for unsupported inherited BUY/SELL currencies. `tests/test_degiro_trades.py` and `tests/test_degiro_dividends.py` require matching source and quote currencies.

#### Scenario: Read currencies independently of arithmetic support

- **WHEN** `.venv/bin/python -m pytest -q tests/test_currency_evidence.py` runs explicit and inherited CAD, CHF, GBP and JPY, missing fields, conflicting profiles, unknown units and currencies with zero, two, three or four minor-unit digits
- **THEN** compatible codes are recognized, raw evidence is unchanged, invalid inheritance stays unavailable, and arithmetic requires a proved unit rather than a two-decimal default.

#### Scenario: Exact major and derived quote units

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_trades.py tests/test_degiro_dividends.py` runs verified currency and quote-unit pairs, repeated conversion, wrong factors and unsupported pairs
- **THEN** prices, fees and dividend amounts preserve their value, quantity does not change, and ambiguous units block before writes.
