# Proposal

## Why

DEGIRO still uses a large untyped script and an old IBKR core. Adopt the complete common foundation defined and implemented in IBKR v3.0.0. A file split alone does not meet this goal.

## What Changes

- Adopt typed modules, immutable data classes, strict checks and the installed Docker module command. Use Python 3.14 as IBKR does.
- Extend the byte projection to selected units from multiple source files. Adopt the reviewed v3.0.0 Ghostfolio helpers and their required dependencies in this change.
- Adopt applicable authentication, simulation, identity, exact acceptance, reporting, notification and native evidence contracts. Map every IBKR requirement to an implementation task or an explicit broker-specific difference.
- Introduce versioned DEGIRO identities with a dual reader. Keep existing rows. Report differences before deduplication hides them.
- Adopt candidate/stable publication rules. Reuse the existing connector lab with a dedicated DEGIRO container, private state and credentials. Require empty and golden-copy acceptance.
- **BREAKING:** replace the old script command with `python -m ghostfolio_degiro_sync`; align blank simulation settings and failure notifications with IBKR. Preserve DEGIRO's stronger financial fences.

Inventory: existing observed-data record `docs/source-contract.md`, accepted accounting spec and `cash-rules.yaml`. Broker source unchanged; no new real-data claim.

| DEGIRO event | Scope |
| --- | --- |
| BUY/SELL | Preserve conversion and units |
| Paid dividend; withholding | Preserve exact pairing |
| Brokerage; AutoFX | Preserve execution fees |
| Exchange connection charge | Preserve FEE and prove UUID readback |
| Flatex interest; fund compensation | Preserve INTEREST and prove UUID readback |
| FX debit/credit; withdrawal/funding | Preserve cash-only rules and unknown-funding refusal |
| Sweep notice/transfer; execution cash | Preserve classification and checks |
| Announced dividend | Preserve exclusion |
| Legacy fund NAV/transaction; corporate action; unknown event | Preserve refusal; new support excluded |

## Capabilities

### New Capabilities

- `shared-ghostfolio-core`: reviewed multi-source projection and provenance.
- `release-publication`: immutable candidates, stable promotion and lab acceptance.

### Modified Capabilities

- `degiro-synchronization`: common runtime, identities, acceptance, diagnostics and native evidence, with DEGIRO accounting retained.

## Non-goals

IBKR Flex parsing, new DEGIRO financial products, a shared library, automatic historical conversion, production deployment or financial writes.

## Impact

Runtime, generated core, tests, image, CI and existing guidance. Approval changes the implementation scope; it does not authorize publication or live operations.
