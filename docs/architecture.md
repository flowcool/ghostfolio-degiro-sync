# Architecture

This describes the current implementation. [ADR-0002](adr/0002-durable-account-execution.md)
records an accepted deepening direction that has not yet changed the implementation.
[GLOSSARY.md](../GLOSSARY.md) defines the domain terms. README owns deployment and
configuration; the topical contracts below own financial and recovery behavior.

## Module responsibilities

| Module | Current location | Responsibility and seam |
| --- | --- | --- |
| Command orchestration | `degiro_to_ghostfolio.py`: `main`, `run_sync`, `run_sync_locked` | Validate configuration and dates, select a mode, hold the applicable account lock, authenticate and acquire evidence before synchronization. |
| Broker reading | `degiro_to_ghostfolio.py`: `read_degiro` and broker/vault helpers | Fresh vault retrieval, bounded login/read/logout, raw history overlap checks and requested statement/holdings acquisition. |
| Ghostfolio transport | `degiro_to_ghostfolio.py`: authentication helpers and `ghost_transport` | Bind the immutable core to the configured origin and permitted routes; enforce DRY_RUN and restore the sequential per-run binding. |
| Account evidence and proposal | `degiro_to_ghostfolio.py`: `synchronize_locked`, `rolling_snapshot`, `prospective_snapshot` | Validate ownership, source and destination evidence, normalize activities, match existing activities and prove holdings before dispatch. |
| Cash accounting | `degiro_to_ghostfolio.py`: cash classification, dividend/fee/yield normalization and current-cash checks | Apply the rules taxonomy, preserve payment identities, associate withholding and execution costs, and verify fresh cash independently of historical balances. |
| Journal and recovery | `degiro_to_ghostfolio.py`: `account_journal`, intent helpers and readback helpers | Lock destination ownership, persist private account state, retain pending requests and verify selected imports before local confirmation. |
| Immutable core | `ghostfolio_core.py` | Pinned broker-independent account/import/cash behavior, projected byte-for-byte under CORE_PROVENANCE.md. |

These are conceptual modules, mostly implemented as functions in the adapter.
Moving functions to files alone would not reduce their interface knowledge.

## Execution order

The normal rolling command follows this sequence:

```mermaid
flowchart TD
    Config[Configuration and requested dates] --> Lock[Private destination account lock]
    Lock --> Auth[One Ghostfolio authentication]
    Auth --> Broker[Fresh vault retrieval and bounded broker read]
    Broker --> Destination[Destination account and complete activity reads]
    Destination --> Recovery[Check pending import using exact positive readback]
    Recovery --> Preflight[Whole-account evidence and proposal]
    Preflight --> Mode{DRY_RUN}
    Mode -->|yes| Proposal[Return proposal without financial dispatch]
    Mode -->|no| Imports[Intent and exact acceptance for non-SELL then SELL batches]
    Imports --> Cash[Cash intent and confirmation]
    Cash --> Coverage[Persist rolling coverage]
```

The lock covers acquisition as well as dispatch on the command path. The
snapshot-based `synchronize_account` seam locks reconciliation and dispatch,
but its caller supplies already acquired evidence. Full-history DRY_RUN can
run without a journal; rolling and prospective DRY_RUN hold the account lock.

Authentication POSTs are allowed in DRY_RUN. The financial transport blocks
imports and cash updates. Rolling DRY_RUN can verify positive import readback
but preserves a pending intent and does not advance coverage. Before financial
dispatch, relevant unknown or ambiguous evidence blocks the entire account.

## Journal ownership and outcomes

The lock is keyed by Ghostfolio origin and destination account, so a second
source configured for that destination cannot independently acquire ownership.
The journal also binds the source account and rejects an ownership mismatch.
Private state permissions, bounded size and atomic file replacement with file
and directory synchronization belong to the persistence implementation.

| Observation | Current behavior |
| --- | --- |
| Ready account, supported proposal | Persist an import intent before dispatch; accept only exact complete returned evidence. |
| Confirmed non-SELL batch | Update accepted holdings before evaluating the SELL batch. |
| Lost, partial, malformed or changed import outcome | Retain the pending intent and fence further writes and current-cash dispatch. |
| Complete exact positive import readback | Rolling live execution can confirm that import; DRY_RUN preserves it. Explicit recovery selects the request and has a separate local-confirmation option. |
| Absent or partial import readback | Retain uncertainty; no automatic replay or inference of cancellation. |
| Uncertain cash outcome, even if current balance matches | Retain the cash intent; positive import recovery does not apply. |
| Confirmed imports and cash, rolling live execution | Persist rolling coverage after completion. |
| Filesystem failure during persistence | Propagate failure; replacement may already be visible, so do not infer rollback or durability from an exception. |

The journal helpers currently expose a mutable document. Synchronization knows
when to prepare and confirm intents and directly publishes coverage. This is
the interface knowledge ADR-0002 proposes to concentrate; it is not evidence
that the safeguards are absent.

## Mode-specific evidence

| Mode | Evidence and permitted claim |
| --- | --- |
| Full history | Supported historical conversion; live writes require an explicit verified-completeness assertion. Reading many windows does not establish completeness. |
| Rolling | At least 90 days through broker-local today, bounded catch-up against recorded coverage, source statement and holdings proof, destination ownership and manual matching. No claim of complete history or cost basis. |
| Prospective | Proved opening evidence, protected prior destination history, full replay since cutover, source interval and resulting holdings proof. No relabeling of the result as full-history verification. |

Read [source-contract.md](source-contract.md),
[prospective-sync.md](prospective-sync.md), [fee-contract.md](fee-contract.md)
and [interest-compensation-policy.md](interest-compensation-policy.md) before
changing these rules. [Recovery](recovery.md) owns interrupted-request handling;
[authentication](ghostfolio-auth.md) owns credentials and origin policy.
[CORE_PROVENANCE.md](../CORE_PROVENANCE.md) owns projection and propagation.

## Test surface

The existing account-execution interface takes synthetic snapshots and explicit
import/cash callbacks; the real immutable-core writers and synthetic callbacks
are actual adapters at this seam. Recovery has its own selected-request
interface. Real temporary private files exercise persistence and restart
behavior without a second storage adapter.

Keep command-path tests as well: they cover configuration, acquisition date
scope, lock lifetime, one authentication and DRY_RUN transport policy that
snapshot-based tests cannot prove. Existing synchronization, rolling,
prospective, authentication and recovery regressions provide prior art.
Observe proposals, accepted evidence, dispatch order, durable state and
subsequent behavior; avoid asserting an internal helper call graph.

Broker/vault retrieval and bounded transports already hide substantial
implementation behind small interfaces. Their file size alone is not a
reason to add another seam. The core transport binding is sequential and
must not be interpreted as support for concurrent account execution in threads.
