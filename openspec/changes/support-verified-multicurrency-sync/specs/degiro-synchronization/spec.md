# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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

Current cash MUST come from fresh DEGIRO evidence and never from old ledger balances. The connector SHALL keep one configured Ghostfolio account. Its currency SHALL equal the broker base currency. Where foreign cash exists, the proposed balance SHALL be the broker-reported aggregate already expressed in that base currency. A list of currency balances alone SHALL NOT establish an aggregate.

The aggregate SHALL have proved field meaning, currency, current source-account binding, complete component coverage and independent consistency checks. Missing, duplicate, contradictory, stale or unqualified evidence SHALL block before any financial write. Unproved nonzero components SHALL NOT become zero. Cash aliases and pseudo-positions SHALL remain corroboration, not extra balances to add. A verified aggregate SHALL be accepted when positive, zero or negative. Its sign SHALL NOT change its source meaning or authorize a broker transaction. Nonzero settlement and new cash/income categories SHALL retain refusal until separately qualified; the connector SHALL NOT invent settled cash.

The connector SHALL NOT calculate a substitute aggregate from external rates, trade rates or a sum of unlike currencies. It SHALL NOT create accounts or change the configured account currency. Existing EUR-only evidence SHALL keep its current verification path. Other base currencies and nonzero foreign cash SHALL require the same proved aggregate contract. Recognition of a currency SHALL NOT claim that an unobserved DEGIRO cash layout has been qualified.

A one-cent statement difference SHALL remain accepted only under its existing corroborated execution rule. This change SHALL NOT extend that tolerance to other categories or monetary scales. DRY_RUN SHALL authenticate, read, log proposals and the cash change, write nothing and not advance coverage.

Simulation values SHALL be trimmed and case-insensitive. Absent or blank DRY_RUN SHALL emit `DRY_RUN not set: simulation, nothing written` once per invocation, including configuration failure. Invalid DRY_RUN SHALL fail before broker/Ghostfolio HTTP. Each failed invocation SHALL attempt exactly one sanitized failure notification when configured, in manual and scheduled simulation or live mode. This grants no financial access. Successful simulation SHALL remain silent. Delivery failure SHALL preserve the original exit status.

Exception: explicit live mode forced into simulation by missing/invalid TZ SHALL send one configured summary naming that reason, even on success. A failure SHALL take precedence and use one failure summary, never a second dispatch. No new token-expiry reminder mechanism is required.

Ghostfolio account list/detail reads SHALL use a 120-second inactivity timeout; cash PUT SHALL retain 30 seconds. Authentication SHALL retain connect/read timeouts of 10/30 seconds. Existing origin checks, disabled ambient proxies, redirect refusal and secret-free diagnostics SHALL remain.

#### Scenario: Cash and failure contracts

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_notify.py tests/test_foundation_runtime.py tests/test_ghostfolio_auth.py` runs existing EUR cases and qualified synthetic aggregate cases
- **THEN** currency, freshness, coverage and exact cash guards pass; simulation sends no financial writes; invalid inputs and failed delivery preserve the notification contract; account reads use 120 seconds and cash writes use 30 seconds.

#### Scenario: One account with foreign cash

- **WHEN** `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_rolling.py` runs a qualified positive, zero or negative broker aggregate, nonzero foreign components, duplicate aliases, missing base denomination and an unqualified layout
- **THEN** the qualified case proposes only the reported base-currency aggregate for the existing account; uncertain cases refuse before imports or cash writes, without a local FX calculation or account creation.

#### Scenario: Rounding in simulation

- **WHEN** `docker compose up` runs under authorized DRY_RUN against a qualified snapshot with one supported execution-cent rounding difference
- **THEN** logs show `Cash statement verified with 1 corroborated one-cent execution rounding differences` and `(no update sent)`.

Baseline changed: `tests/test_degiro_cash.py` permits only EUR, zero foreign components and exact agreeing EUR aliases. `docs/source-contract.md` records that observed configuration. The meaning and cross-checks of a nonzero multicurrency aggregate remain an implementation qualification gate, not an asserted broker fact. Notification and transport baselines remain `tests/test_notify.py` and `docs/ghostfolio-auth.md`.

### Requirement: Exact read-only reconciliation

DRY_RUN SHALL compare source events with owned destination activities before import deduplication. It SHALL retain exact original numeric evidence, normalize only proven supported currency units and distinguish coherent, informational, noise, to-check, uncertain and outside-window findings. Every in-scope source event and destination activity SHALL be accounted for once; ownership contention SHALL remain uncertain. Missing security, currency, date or quantity proof SHALL remain unavailable. Dividend activity quantity 1 SHALL NOT be presented as proven security quantity.

The report SHALL show expected/observed identity and financial checks, one Action line per block and an explicit statement that nothing was written. Display rounding SHALL use proved currency minor units without changing comparison. No Python representations or exponent notation SHALL appear. Candidate proposals SHALL identify the compared activity; weak matches SHALL not claim a row to keep. Quantity has zero tolerance. No generic amount threshold or IBKR-only declared-rate cause SHALL be imported into DEGIRO. Any accepted difference SHALL name its existing proven DEGIRO cause.

The report SHALL distinguish a raw currency, a currency resolved from the same activity profile and an unavailable unit. It SHALL explain historical evidence that does not affect selection without marking it financially verified. For cash, it SHALL identify the broker base currency and reported aggregate separately from original currency components. It SHALL NOT display a hypothetical sum as available cash or claim that missing broker evidence has been qualified.

Reporting SHALL reuse the existing reads without writes, extra broker/Ghostfolio reads or input replacement. Findings SHALL not change selection, exits or notifications. Technical failures retain their failure contract. Live sync SHALL not run the historical report.

#### Scenario: Exact and readable findings

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_diagnostics.py tests/test_simulation_review.py` runs exact decimals, ambiguous ownership, split rows, wrong action targets, new currencies, quantity differences and outside-window history
- **THEN** deterministic findings conserve coverage, retain uncertainty and exact comparison, use plain display with currency provenance, and leave import payloads, HTTP counts, exits and notifications unchanged.

Baseline: the same tests and `ghostfolio_degiro_sync/diagnostics.py` already preserve raw numbers and observational reports. This change extends unit coverage and cash explanation.

## Reference evidence

- [SIX ISO 4217 maintenance](https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html): standard codes and minor units. Implementation must record the exact reference-data snapshot and its hash.
- Ghostfolio 3.99.0, commit `d278362d394a1c49c9cc55e9db4be9a7fd17c7dd`: [account and balance model](https://github.com/ghostfolio/ghostfolio/blob/d278362d394a1c49c9cc55e9db4be9a7fd17c7dd/prisma/schema.prisma), [currency validation](https://github.com/ghostfolio/ghostfolio/blob/d278362d394a1c49c9cc55e9db4be9a7fd17c7dd/libs/common/src/lib/helper.ts), and [derived currency factors](https://github.com/ghostfolio/ghostfolio/blob/d278362d394a1c49c9cc55e9db4be9a7fd17c7dd/libs/common/src/lib/config.ts). These constrain the representation; they do not prove DEGIRO payload semantics.
- IBKR connector reference commit `66d2cea232b65250dffa76818497332a75ac3184`: `ghostfolio_ibkr_sync/ghostfolio.py` currency-evidence mechanism and `ghostfolio_ibkr_sync/ibkr.py` reported base-summary principle. These are design references. The DEGIRO generated-core pin remains unchanged.
