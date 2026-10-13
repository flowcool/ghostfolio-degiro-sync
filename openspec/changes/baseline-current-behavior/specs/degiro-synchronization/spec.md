# Current DEGIRO synchronization

## Purpose

Describe how the connector copies one DEGIRO account into one existing Ghostfolio account today, and when it refuses.

## ADDED Requirements

### Requirement: Supported deployment

The supported deployment SHALL be `compose.yaml`: settings from ENV, DEGIRO login only from one Bitwarden/Vaultwarden item, exactly one Ghostfolio credential, `SYNC_MODE=rolling`, 90 days, `TZ=Europe/Zurich`. `DRY_RUN` absent or `1`/`true`/`yes`/`on` SHALL simulate; `0`/`false`/`no`/`off` SHALL write; another value SHALL stop before broker access. Empty `CRON` SHALL run once; a `CRON` that is not five numeric fields SHALL stop before the connector starts. `APPRISE_URLS` SHALL send failure alerts without secrets.

#### Scenario: Invalid schedule

- **WHEN** `CRON='bad cron' bash entrypoint.sh` runs
- **THEN** it prints `Invalid CRON: expected five numeric schedule fields` and exits 1.

Proof: README lines 92-120; `entrypoint.sh`, replayed 2026-10-13. `DRY_RUN` values: `.venv/bin/python -m pytest -q tests/test_degiro_sync.py -k 'defaults_dry_run or invalid_config_rejected'` reports passed.

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

The connector SHALL produce BUY/SELL; gross DIVIDEND with its one matching tax as fee; FEE for an exchange connection charge; INTEREST of zero for EUR Flatex interest; separate INTEREST for positive EUR fund compensation. Brokerage and currency conversion cost SHALL go into the execution fee. Currency exchange, withdrawals, cash sweeps and execution cash rows SHALL create no activity. Announced dividends SHALL be ignored. Prices MUST be EUR, USD or JPY; instruments MUST be STOCK with contract size 1.

#### Scenario: Supported events

- **WHEN** the accounting tests run
- **THEN** amounts, currencies and identities are kept, without duplicate fees or guessed tax.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_trades.py tests/test_degiro_dividends.py tests/test_degiro_fees.py tests/test_degiro_cash_yield.py` reports passed. The 2026-10-10 real DRY_RUN proposed one zero Flatex INTEREST and one positive compensation INTEREST.

### Requirement: Whole-account refusal

Unknown or unsupported data, a tax without exactly one matching dividend, wrong units or a changed identity MUST stop all writes for the account. Old fund history and corporate actions are unsupported.

#### Scenario: Unsupported evidence

- **WHEN** such data is present
- **THEN** logs show `DEGIRO sync failed; unknown, incomplete or uncertain account state blocks writes` and nothing is written.

Proof: `.venv/bin/python -m pytest -q tests/test_degiro_sync.py tests/test_degiro_dividends.py -k 'whole_account or ambiguous or unsupported or unknown'` reports passed.

### Requirement: Cash check and simulation

Current EUR cash MUST come from DEGIRO, match the statement and never be rebuilt from old balances. A one-cent difference SHALL be accepted only when its execution amount confirms it; any other difference MUST stop writes. DRY_RUN SHALL authenticate, read, log proposals and the cash change, write nothing and not advance coverage.

#### Scenario: Rounding in simulation

- **WHEN** `docker compose up` runs with `DRY_RUN=1` and an execution has a one-cent rounding
- **THEN** logs show `Cash statement verified with 1 corroborated one-cent execution rounding differences` and `(no update sent)`.

Proof: retained real DRY_RUN, 2026-10-10. Offline: `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_simulation_review.py tests/test_ghostfolio_auth.py` and `.venv/bin/python -m pytest -q tests/test_prospective.py -k 'cent or rounding'` report passed.

### Requirement: Additive import and recovery

Imports SHALL keep existing activities, skip known duplicates and record write intent first. Rolling matching with manual activities SHALL not certify history. After a lost reply, an exact readback MUST confirm the import; until then, writes and cash updates stay blocked.

#### Scenario: Repeated or interrupted import

- **WHEN** an accepted import repeats or its reply is lost
- **THEN** no duplicate is created; an incomplete readback blocks further writes.

Proof: `.venv/bin/python -m pytest -q tests/test_rolling.py tests/test_degiro_sync.py tests/test_degiro_recovery.py` reports passed.
