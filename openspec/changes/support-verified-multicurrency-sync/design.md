# Design

## Context

See proposal.md. `accounting.CURRENCY_QUANTA` currently supplies read eligibility and arithmetic precision. `ghostfolio.index_existing_activities` consequently rejects inherited CAD dividends. Cash admission assumes EUR-only funds.

## Goals / Non-Goals

Implement the general contract without changing authentication, journal format, instrument classes or the generated core. Keep one existing destination account.

## Decisions

- **Evidence:** adapt `ghostfolio_ibkr_sync/ghostfolio.py`'s `CurrencyEvidence` and `effective_currency` mechanism. Keep raw/effective values, origin and refusal reason. A missing field differs from null. Destination compatibility does not authorize accounting.
- **Units:** use a packaged keyed YAML currency registry with reference dates, hashes and source URLs. Derive standard minor units from SIX ISO 4217 data. Verify destination acceptance against Ghostfolio's validator. Reuse the sibling's major/derived-unit distinction, but require explicit verified mapping rather than its ticker-suffix inference. Use exact Decimal factors; do not add a runtime lookup or dependency.
- **History:** retain complete rows and global ownership checks. Assess required evidence in `select_account_activities` before allowing unavailable historical monetary units. Include manual-match margins, holding quantities and pending recovery. CAD is an ordinary recognized currency, not an exception.
- **Cash:** reuse the sibling's `ibkr.parse_cash_report` principle: consume the broker's base-currency aggregate. Keep DEGIRO-specific verification in `current_cash_balance`; recognize typed CASH rows before security-ID decoding in both broker reading and holdings selection. Reuse the immutable `ghost_update_cash_balance` writer and durable intent. Do not copy IBKR XML fields into DEGIRO or construct a replacement aggregate.
- **Reports:** reuse existing diagnostic reads and exact decimal comparison. Show provenance and unavailable evidence without changing selection.

## Risks / Trade-offs

- Unproved aggregate semantics: block that cash layout. Existing evidence proves only EUR with zero foreign components. Source evidence must establish base denomination and independent checks before enabling nonzero foreign cash.
- Valid codes with unknown monetary units: allow evidenced reads; refuse required arithmetic. No default two-decimal rule.
- Historical admission hides a control: test ownership, match boundaries, quantities and recovery before dispatch.

## Migration Plan

Use one branch and PR. Prove synthetic regressions and retained offline admission. Qualify the exact image in both labs. Release and Infra activation retain their own authority. Roll back code atomically; prove old-reader compatibility before using it after new-currency writes.

## Open Questions

Which retained DEGIRO fields prove aggregate denomination and component coverage with nonzero foreign cash? Resolve the evidence gate before enabling that layout; obtain any fresh capture through the existing Infra operation.
