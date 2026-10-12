---
status: accepted
date: 2026-10-10
---

# Retain uncertainty until exact request-bound completion is proved

Resolve a pending import only from complete, unique positive readback of all
expected identities and financial fields under the account ownership lock and
the explicitly selected request ID. Preview retains state; explicit local
confirmation changes only that journal. Rolling live synchronization may confirm
the same exact positive evidence, while DRY_RUN retains the pending intent.

Empty or partial readback cannot prove cancellation: delayed server work can
still finish. A matching cash balance cannot prove completion of an old PUT.
Automatic replay, deletion, journal erasure and cash resolution from balance
alone are rejected. Production cancellation requires an independently proved,
request-bound procedure and separate operator authorization.

The [isolated acceptance evidence](../isolated-acceptance.md) demonstrates delayed
completion and owned-server quiescence only in disposable synthetic instances.
It does not prove production topology or grant authority to interrupt a shared
service. The [recovery contract](../recovery.md) owns commands, evidence and
rollback; preserve journals when reverting source or images.
