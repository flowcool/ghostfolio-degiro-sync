# Proposal

## Why

Record demonstrated behavior before future changes, without changing execution.

## What Changes

Document all three modes and their agreed evidence boundaries.

Inventory: retained French API capture, 2026-10-09; three SELL executions, 88 cash rows, twelve configured categories. BUY is demonstrated offline. Absent cases are marked separately.

| DEGIRO event considered | In scope: current treatment | Out of scope |
| --- | --- | --- |
| Executed BUY / SELL | BUY / SELL activities | Unsupported instruments or units |
| Paid dividend | Gross DIVIDEND | Unpaid announcements |
| Dividend withholding | Unique linked dividend fee | Unproved association |
| Brokerage | Execution fee | Separate duplicate FEE |
| AutoFX execution cost | Execution fee | Unproved conversion |
| Exchange connection charge | Standalone FEE | Other uncharacterized charges |
| FX debit | Cash-only control | Separate activity |
| FX credit | Cash-only control | Separate activity |
| Bank withdrawal | Cash-only control | Separate activity |
| Sweep annotation | Nonfinancial notice | Notice with an amount |
| Sweep transfer | Cash-only control | Separate activity |
| Execution cash row | Corroborates execution | Second trade |
| Zero EUR Flatex interest | Zero INTEREST | Nonzero interest |
| Positive EUR fund compensation | Distinct INTEREST | Zero/negative compensation |
| Legacy fund NAV/transactions; corporate actions; deposits; security transfers; unknown events, absent from selected capture | Refusal when relevant | Import support |

EUR cash is independently verified. Quotes: EUR/USD/JPY. Statement relationships: French.

## Capabilities

### New Capabilities

- `degiro-synchronization`: reference for existing modes, accounting, safeguards and deployment.

### Modified Capabilities

None.

## Impact

OpenSpec artifacts only; no runtime changes.

## Non-goals

Exhaustive history, certified cost basis, unsupported events, correction/deletion, deployment or activation. Exhaustive `full_history` requires a separate change.
