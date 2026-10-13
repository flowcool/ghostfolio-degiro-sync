# Proposal

## Why

Record what the connector does today, before any change. Runtime behavior does not change.

## What Changes

Describe the three sync modes, accounting, safety checks and deployment as observed.

Evidence: a read-only French DEGIRO capture of one year (2025-10-08 to 2026-10-08, saved 2026-10-09) with three SELL executions, 88 cash rows and all twelve rules of `cash-rules.yaml`. A real read-only rolling DRY_RUN on 2026-10-10 covered 90 days only: one SELL, 15 cash rows, nine of the twelve rules. BUY is proven by offline tests only.

| DEGIRO event considered | Treatment today | Out of scope |
| --- | --- | --- |
| Executed BUY / SELL | BUY / SELL activity | Other instrument types or units |
| Paid dividend | Gross DIVIDEND | Announced, unpaid dividend |
| Dividend tax | Fee on its one matching dividend | Tax without exactly one dividend |
| Brokerage fee | Fee on its execution | Separate FEE activity |
| Currency conversion cost (execution field, no cash row) | Fee on its execution | Cost without its execution |
| Exchange connection charge | FEE activity | Other unknown charges |
| Currency exchange debit / credit | Cash check only | Activity |
| Bank withdrawal | Cash check only | Activity |
| Cash sweep transfer | Cash check only | Activity |
| Cash sweep text without amount | Ignored notice | Same text with an amount |
| Execution cash row | Confirms its execution | Second trade |
| Flatex interest, EUR, zero | INTEREST of zero | Interest above zero |
| Money market fund compensation, EUR, positive | Separate INTEREST | Zero or negative amount |
| Not in the capture: old fund history, corporate actions, deposits, security transfers, unknown events | Run stops when present | Import |

Current EUR cash comes from DEGIRO and must match the statement; a one-cent difference is accepted only when its execution confirms it. Price currencies: EUR, USD, JPY. Statement text: French.

## Capabilities

### New Capabilities

- `degiro-synchronization`: reference for existing modes, accounting, safety checks and deployment.

### Modified Capabilities

None.

## Impact

OpenSpec artifacts only; no runtime changes.

## Non-goals

Exhaustive history, certified cost basis, unsupported events, correction or deletion, deployment or activation. Exhaustive `full_history` needs a separate change.
