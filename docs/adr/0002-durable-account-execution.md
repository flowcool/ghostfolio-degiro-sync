---
status: accepted
---

# Concentrate durable account execution in the adapter

The journal currently exposes pending intent and coverage representation, while
synchronization and recovery carry completion-ordering knowledge. Deepen durable
account execution inside the adapter so intent preparation, exact acceptance,
uncertainty fencing and completion publication gain locality behind a smaller
interface, preserving whole-account preflight and existing import/cash dispatch
adapters; retain the current disk implementation instead of adding a speculative
storage abstraction.

This is an accepted design direction, not an implemented refactor. The existing
account-execution and selected-import recovery seams remain the primary test
surface, with full command paths covering acquisition and transport ordering.
Preserve the journal format and ownership lock, import-versus-cash recovery
rules, DRY_RUN behavior and immutable core. File splitting, a generic retry
framework and a shared sibling refactor would increase scope without earning
this depth. Cash-processing and mode-preparation deepening remain separate
opportunities rather than commitments in this decision.
