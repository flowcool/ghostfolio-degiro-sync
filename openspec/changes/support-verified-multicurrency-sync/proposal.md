# Proposal

## Why

The connector confuses currencies accepted by Ghostfolio with the three currencies previously tested for DEGIRO accounting. This blocks valid historical dividends and prevents general currency support.

## What Changes

- Separate currency recognition, exact unit conversion and financial evidence.
- Accept compatible currencies through versioned reference data, without an EUR/USD/JPY restriction.
- Preserve original currency evidence. Resolve a null activity currency only from that activity's own valid profile.
- Keep structurally valid historical data when unavailable monetary evidence does not affect the operation. Require proof for holdings, matching, ownership and recovery.
- Keep one Ghostfolio account. Set cash to DEGIRO's verified aggregate in its base currency. Do not calculate a replacement aggregate or create currency accounts.
- Explain unavailable units and unqualified cash cases without exposing private data.

### Event scope

The source remains the saved French DEGIRO contract in `docs/source-contract.md`, `ghostfolio_degiro_sync/cash-rules.yaml` and `tests/fixtures/degiro_contract.yaml`.

| Event or observation | Scope |
| --- | --- |
| STOCK BUY/SELL, contract size 1 | Compatible currencies and proven quote units |
| Paid dividend and paired withholding | Compatible currencies and proven quote units |
| Brokerage and AutoFX fee | Existing execution-cost reconciliation |
| Annual connection fee | Existing EUR FEE policy |
| FX debit/credit | Cash evidence; no activity |
| Withdrawal/funding | Existing recognized cash-only categories |
| Sweep annotation/transfer | Existing notice/cash-only treatment |
| Execution cash row | Existing statement reconciliation |
| Zero Flatex interest | Existing EUR convention |
| Positive monetary-fund compensation | Existing EUR convention |
| Announced dividend | No activity |
| Current foreign-currency cash | Verified broker base-currency aggregate |
| Legacy fund NAV/transactions, corporate actions, unknown categories | Remain blocked when relevant |

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `degiro-synchronization`: general currency evidence, relevant-data refusal, quote units and aggregate cash.

## Impact

Adapter configuration, accounting, destination reads, selection, broker cash classification and reports change. README and source/recovery documentation describe the contract. Reuse existing mechanisms before adding a module. Generated core, authentication, ownership grammar and default deployment remain unchanged. Exact-image qualification uses both existing labs.

## Non-goals

No automatic FX trading, external-rate cash calculation, multiple destination accounts, instrument-class expansion, new income policy, historical conversion, production activation or stable publication.
