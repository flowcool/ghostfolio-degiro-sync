# Tasks

All requirement and scenario names below refer to `specs/degiro-synchronization/spec.md` in this change. Start implementation after approval of these artifacts. Add each regression before its fix. Use disposable state and synthetic inputs for tests. Replay retained private evidence separately, offline, without altering it.

## 1. Currency evidence

- [x] 1.1 Separate destination recognition from monetary units. Add a versioned keyed currency registry with authoritative source dates and hashes. Cover valid explicit/profile currencies, missing versus null fields, invalid current profiles, unknown units and 0/2/3/4 decimal scales. Preserve raw evidence. Requirement: Currency evidence and units. Scenario: Read currencies independently of arithmetic support. Files: `ghostfolio_degiro_sync/currencies.py`, `ghostfolio_degiro_sync/currency-units.yaml`, `ghostfolio_degiro_sync/models.py`, package resource configuration if required, `tests/test_currency_evidence.py`; update `docs/source-contract.md` with reference-data scope. Acceptance: `.venv/bin/python -m pytest -q tests/test_currency_evidence.py`.

## 2. Existing activities and recovery

- [x] 2.1 Apply currency evidence to selected-account admission and exact accepted-result/recovery checks. Retain complete rows and quantity evidence. Permit unavailable old monetary units only after proving that no ownership, holding, protected-history, recovery or manual-match control needs them. Cover multiple currencies and the dividend match margin; do not special-case CAD, an activity ID or a date. Requirements: Selected-account refusal; Currency evidence and units. Scenarios: Historical currencies without a special-case exception; Unsupported selected-account evidence. Files: `ghostfolio_degiro_sync/ghostfolio.py`, `ghostfolio_degiro_sync/sync.py`, `ghostfolio_degiro_sync/journal.py`, `tests/test_foundation_acceptance.py`, `tests/test_rolling.py`, `tests/test_degiro_recovery.py`; update `docs/recovery.md` only for the changed evidence boundary. Acceptance: `.venv/bin/python -m pytest -q tests/test_foundation_acceptance.py tests/test_rolling.py tests/test_degiro_recovery.py`; replay retained destination admission and compare all input hashes and position quantities.

## 3. Trade and dividend currencies

- [x] 3.1 Admit compatible trade currencies and explicit quote-unit relationships through the existing mapping. Convert prices and fees exactly once; preserve quantities, execution identities, base-total/FX checks and existing amount tolerances. Reject unproved pairs and instrument classes. Requirements: Supported accounting; Currency evidence and units. Scenarios: Supported events; Exact major and derived quote units. Files: `ghostfolio_degiro_sync/accounting.py`, `ghostfolio_degiro_sync/config.py`, `ghostfolio_degiro_sync/currencies.py`, `tests/test_degiro_trades.py`; update README mapping examples and `docs/source-contract.md`. Acceptance: `.venv/bin/python -m pytest -q tests/test_degiro_trades.py`.

- [x] 3.2 Apply the same verified units to gross dividends and paired withholding. Keep exact pairing and source identity, preserve the EUR standalone-fee and income conventions, and reject missing or ambiguous tax evidence. Requirements: Supported accounting; Currency evidence and units. Scenarios: Supported events; Exact major and derived quote units. Files: `ghostfolio_degiro_sync/accounting.py`, `tests/test_degiro_dividends.py`, `tests/test_degiro_fees.py`, `tests/test_degiro_cash_yield.py`; update `docs/source-contract.md` for dividend units. Acceptance: `.venv/bin/python -m pytest -q tests/test_degiro_dividends.py tests/test_degiro_fees.py tests/test_degiro_cash_yield.py`.

## 4. Broker cash aggregate

- [x] 4.1 Classify typed cash positions before security metadata lookup in both reading and position reconciliation. Preserve original component currencies and require unique complete current evidence. Requirement: Cash check and simulation. Scenario: One EUR account with foreign-cash refusal. Files: `ghostfolio_degiro_sync/degiro.py`, `ghostfolio_degiro_sync/sync.py`, `ghostfolio_degiro_sync/accounting.py`, `tests/test_degiro_read.py`, `tests/test_rolling.py`; update `docs/source-contract.md` to distinguish cash from securities. Acceptance: `.venv/bin/python -m pytest -q tests/test_degiro_read.py tests/test_rolling.py`.

- [x] 4.2 Accept positive, zero and negative verified totals in the existing EUR-only layout. Preserve exact source binding, freshness, complete components, agreeing aliases and zero settlement. Refuse nonzero foreign components, other base currencies, duplicate aliases, missing base denomination and unqualified layouts before dispatch. Do not calculate replacement FX or create accounts. Nonzero foreign-cash qualification is deferred under the operator's explicit 2026-11-16 release boundary. Requirements: Cash check and simulation. Scenarios: Cash and failure contracts; One EUR account with foreign-cash refusal. Files: `ghostfolio_degiro_sync/accounting.py`, `tests/test_degiro_cash.py`, `tests/test_rolling.py`, `docs/source-contract.md`, README. Acceptance: `.venv/bin/python -m pytest -q tests/test_degiro_cash.py tests/test_rolling.py`.

## 5. User-visible results

- [x] 5.1 Show currency provenance, unavailable historical evidence and the broker cash aggregate in simulation output. Preserve observational behavior, HTTP counts, exit status and notifications. Requirements: Exact read-only reconciliation; Cash check and simulation. Scenarios: Exact and readable findings; Cash and failure contracts. Files: `ghostfolio_degiro_sync/diagnostics.py`, `ghostfolio_degiro_sync/app.py`, `tests/test_foundation_diagnostics.py`, `tests/test_simulation_review.py`; finish the README explanation of one account, compatible units and unverified history. Acceptance: `.venv/bin/python -m pytest -q tests/test_foundation_diagnostics.py tests/test_simulation_review.py`.

## Delivery acceptance

Before committing shipped code, run touched-file type checks, `.venv/bin/python -m pytest -q`, and `.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main`. Inspect semantic diff, numstat and whitespace. Run the exact candidate image in the empty and golden labs, including compatible new currencies, derived units, repeat deduplication, aggregate cash, uncertain-stop behavior and unchanged historical rows. Retain the exact image proof and stop both reserved labs.

Use one branch and PR for the deliverable. Apply the repository review/merge gate if publication is requested. Archive this change in the final implementation commit after proof passes. Release preparation and the returned immutable artifact remain in the owning work chain. Stable publication and Infra production activation keep their separate authority. A successful synthetic or lab result does not close real-history acceptance or replace a fresh authorized production preview.

## Release boundary

The operator approved this release on 2026-11-16 with compatible trade/dividend currencies and verified signed EUR cash. Nonzero foreign cash remains refused and is tracked separately. All seven offline slices pass their targeted checks. Exact-image native acceptance and final release qualification are required before delivery. Real-history acceptance remains independent.
