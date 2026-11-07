# Proposal

## Why

DEGIRO reports a version only at container startup. It omits the source commit and each scheduled cycle's identity. Stable publication rebuilds the candidate, although current project guidance requires the qualified digest.

## What Changes

- Derive the target version and full commit from the exact release tag and Git commit.
- Print the identity at container startup and each application cycle.
- Print a fixed `DEGIRO SYNC` ASCII banner once at connector container startup.
- Promote the qualified RC index without rebuilding. Verify both architectures, source identity, qualification evidence and its signature.
- Preserve DEGIRO's `v`-prefixed image tags.

The event inventory below comes from the retained characterization summarized in `docs/source-contract.md` and the current accounting specification. This change reads no new broker data and changes no source.

| Event type considered | Scope |
| --- | --- |
| BUY, SELL | Out: preserve conversion and matching |
| Paid DIVIDEND, withholding | Out: preserve exact pairing and fee |
| Brokerage, AutoFX, exchange FEE | Out: preserve fee classification |
| Zero Flatex INTEREST, fund COMPENSATION | Out: preserve separate identities |
| FX, funding, withdrawals, cash sweeps, execution cash | Out: preserve exclusions |
| Announced dividend, legacy fund NAV, corporate action, unknown event | Out: preserve refusal or exclusion |

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `degiro-synchronization`: fixed startup banner and per-cycle software identity.
- `release-publication`: automatic embedded identity and qualified promotion without rebuilding.

## Impact

Affects `Dockerfile`, `entrypoint.sh`, application startup, release helpers, the release workflow, existing runtime checks, README and build guidance. Reuse Git and pinned build actions. Add no runtime renderer or versioning dependency.

## Non-goals

No accounting, transport, journal, snapshot or credential change. No broker login, financial conversion, deployment or stable publication. No automatic core refresh. No new security policy: assess the IBKR secret-scan and Scorecard mechanisms separately.
