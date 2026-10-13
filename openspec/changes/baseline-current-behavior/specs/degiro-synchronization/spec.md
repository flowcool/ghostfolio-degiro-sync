# Current DEGIRO synchronization

## Purpose

Describe demonstrated synchronization behavior and refusal boundaries for one DEGIRO account and one existing Ghostfolio account.

## ADDED Requirements

### Requirement: Supported deployment

The connector SHALL support Compose, environment configuration, vault-only broker credentials, exactly one Ghostfolio credential, optional CRON and sanitized failure alerts.

#### Scenario: Public setup

- **WHEN** the documented Compose setup is selected
- **THEN** rolling90, Europe/Zurich and default DRY_RUN apply.

Proof: README; `sed -n '92,120p' README.md` displays these settings.

### Requirement: Rolling verification

Rolling SHALL read 90 days through broker-local today, including missing pre-service events. Explicit earlier catch-up SHALL cover journaled gaps. Holdings and statements MUST reconcile; historical completeness and cost basis remain unverified.

#### Scenario: Initial run and catch-up

- **WHEN** rolling evidence passes, or an outage needs catch-up
- **THEN** missing activities are proposed; uncovered gaps refuse processing.

Proof: `.venv/bin/python -m pytest -q tests/test_rolling.py` reports passed, including initial-run and catch-up checks.

### Requirement: Prospective verification

Prospective SHALL require a pinned, account-bound opening manifest with matching holdings, preserve legacy history and replay the opening interval through today. Only post-cutover events are eligible; historical basis remains unverified.

#### Scenario: Verified opening

- **WHEN** opening evidence and subsequent history agree
- **THEN** eligible events are proposed; changed opening evidence blocks.

Proof: `.venv/bin/python -m pytest -q tests/test_prospective.py` reports passed.

### Requirement: Full-history limitation

Full_history SHALL use the requested period and block live writes without verified completeness. Selecting it does not establish exhaustive retrieval.

#### Scenario: Unverified completeness

- **WHEN** completeness is unverified
- **THEN** simulation discloses this and live dispatch refuses.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_sync.py -k 'history or whole_account'` reports passed.

### Requirement: Characterized accounting

The connector SHALL produce BUY/SELL, gross DIVIDEND with uniquely linked withholding, standalone connection FEE, zero EUR Flatex INTEREST and distinct positive EUR compensation INTEREST. Brokerage/AutoFX belong to execution fees. Recognized FX, withdrawals, sweeps and execution-cash rows SHALL create no extra activities. Upcoming dividends are excluded. Quotes MUST be EUR/USD/JPY and instruments satisfy STOCK/contract-size 1 checks.

#### Scenario: Supported events

- **WHEN** characterized evidence satisfies its relationships
- **THEN** amounts, currencies and identities are preserved without duplicate fees or inferred tax.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_trades.py tests/test_degiro_dividends.py tests/test_degiro_fees.py tests/test_degiro_cash_yield.py` reports passed.

### Requirement: Whole-account refusal

Unknown or unsupported relevant data, ambiguous dividend/tax links, incompatible units or changed financial identities MUST block account dispatch. Uncharacterized legacy fund history and corporate actions are unsupported.

#### Scenario: Ambiguous or unsupported evidence

- **WHEN** required evidence is missing, ambiguous or unsupported
- **THEN** no financial dispatch is permitted.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_sync.py tests/test_degiro_dividends.py` reports passed.

### Requirement: Independent cash and simulation

Current EUR cash MUST be independently verified, never reconstructed from historical balances. DRY_RUN SHALL display proposals and cash changes, accept nothing and advance no coverage.

#### Scenario: Read-only financial proposal

- **WHEN** DRY_RUN succeeds
- **THEN** authentication and reads occur, with no financial write.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_simulation_review.py tests/test_ghostfolio_auth.py` reports passed.

### Requirement: Additive import and recovery

Imports SHALL preserve existing activities, suppress recognized duplicates and persist write intent. Rolling manual-match heuristics SHALL not certify historical accounting. Uncertain imports require exact readback; uncertain cash remains fenced.

#### Scenario: Repeat or interrupted import

- **WHEN** an offline accepted import repeats or its reply is lost
- **THEN** duplicates are prevented; incomplete readback blocks further writes.

Proof: `.venv/bin/python -m pytest -q tests/test_rolling.py tests/test_degiro_sync.py` reports passed.
