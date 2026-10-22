# Proposal

## Why

DEGIRO uses an untyped script and an old core. Adopt the applicable IBKR v3.0.0 foundation and convert proven historical DEGIRO identities in the same delivery.

## What Changes

- Adopt typed modules, frozen data records, strict checks, Python 3.14 and installed module execution. Keep every intermediate Docker build runnable.
- Adopt the actual v3.0.0 core through an explicit multi-source byte projection. Separate reads, indexing, selection and confirmed-result recording.
- Adopt applicable authentication, simulation, identity, acceptance, reporting, notification and evidence contracts. Map all 41 upstream requirements and explicit DEGIRO differences.
- Use `DEGIRO#v1#<account>:<KIND>:<id>`. Deliver offline migration preview, guarded conversion, inspection and rollback with the dual reader and new writer. Inventory all DEGIRO history, beyond 90 days. Convert only proven identities; report and preserve uncertain rows. Preserve activity IDs, financial fields and profiles.
- Keep image tags `vX.Y.Z` and `vX.Y.Z-rc.N`. Adopt stricter candidate/stable publication rules. Qualify the same candidate in the existing empty/golden lab with dedicated DEGIRO execution and checks. No reader-only release is required.
- **BREAKING:** replace the script path with `python -m ghostfolio_degiro_sync`; align blank simulation and failure alerts; missing/invalid TZ forces simulation. Converted/new identities require the qualified dual reader. Historical conversion remains an explicit operation, never an automatic sync effect.

Inventory: observed-data record `docs/source-contract.md`, accounting spec and `cash-rules.yaml`. Broker source unchanged; no new real-data claim.

| DEGIRO event | Scope |
| --- | --- |
| BUY/SELL | Preserve amounts and units |
| Paid dividend; withholding | Preserve pairing |
| Brokerage; AutoFX | Preserve execution fees |
| Exchange connection charge | Preserve FEE and prove UUID readback |
| Flatex interest; fund compensation | Preserve INTEREST and prove UUID readback |
| FX debit/credit; withdrawal/funding | Preserve cash-only rules and refusal |
| Sweep notice/transfer; execution cash | Preserve classification |
| Announced dividend | Preserve exclusion |
| Legacy fund NAV/transaction; corporate action; unknown event | Preserve refusal; new support excluded |

## Capabilities

### New Capabilities

- `shared-ghostfolio-core`: reviewed multi-source projection and provenance.
- `release-publication`: immutable candidates, stable promotion and lab acceptance.

### Modified Capabilities

- `degiro-synchronization`: common runtime, identities, historical conversion, acceptance, diagnostics and evidence; DEGIRO accounting retained.

## Non-goals

Flex parsing, new financial products, a shared library, financial corrections, automatic conversion, and live operations without explicit authorization.

## Impact

Runtime, core, maintenance commands, tests, image, CI and existing guidance. Publication and real conversion require their recorded GO.
