# Disposable Ghostfolio import and recovery evidence

## Boundary and reproducibility

Run only on a Docker lab host, from this repository, with a locally built adapter
image. This is not pytest, a production canary or a broker login:

```sh
docker build --build-arg TARGETARCH=amd64 --build-arg APP_VERSION=acceptance \
  -t ghostfolio-degiro-sync:acceptance .
.venv/bin/python scripts/isolated_acceptance.py \
  --runtime-image ghostfolio-degiro-sync:acceptance
```

The controller generates a unique Compose project, internal network, disposable
Postgres tmpfs database and Redis. Image digests are pinned in the controller.
There are no published ports, production volumes, operator credentials, DEGIRO
requests or external network access. A rootless adapter worker mounts only the
public synthetic fixture and driver read-only. Ephemeral lab signup credentials
remain in worker memory/environment and never appear in outputs or artifacts.
Generated Compose authentication belongs in a mode0600 temporary file, removed
with the controller's temporary directory. Do not inspect/print that manifest.

Native Ghostfolio is3.81.0 at the pinned image digest, corresponding to official
[source920d0787541a8568920fc11f978aa01e5a52c581](https://github.com/ghostfolio/ghostfolio/tree/920d0787541a8568920fc11f978aa01e5a52c581).
Only one exact compiled Yahoo `getAssetProfile` delegation is replaced with a
TEST/USD named fixture. The replacement rejects every other symbol; a count
assertion fails if the pinned delegation changes. This substitutes external
market resolution, not import/account validation, dedup, returned evidence or
database writes. Those native paths remain byte-identical. The lab therefore
proves transport/DTO/import/recovery behavior; it does not verify real Yahoo
quote currency, live broker data or market-price performance.

## Observed results (2026-10-08 and 2026-10-09)

| Scenario | Exact observed result |
| --- | --- |
| Seeded opening BUY10 TEST/USD | Native account contains one opening row before adapter work |
| Adapter DRY_RUN | Proposes3 rows; stored count remains1; balance remains0 |
| First adapter import | Native SELL2, paid DIVIDEND and FEE preserve all10 canonical DTO fields; net holding8; current balance12.30EUR |
| Repeated full sync | No proposed/imported rows; stored count remains4 |
| Changed configured mapping after native import (2026-10-09) | Same source identities mapped from TEST to CHANGED_TEST with unchanged USD quote currency fail with the exact canonical financial-evidence conflict. Complete native activities and target balance remain unchanged; no pending intent is created |
| Uncertain delayed INSERT | PostgreSQL BEFORE INSERT trigger blocks owned FEE999 on an advisory lock; HTTP times out; complete GET still contains only4 rows |
| New Python process before release | Reads persisted intent and refuses synchronization; empty pending readback refuses resolution; no replay |
| Release owned barrier | Native original request inserts exactly one row; complete count5; old request ID refuses even with positive readback. Rootless recovery CLI obtains authenticated GETs: default preflight retains intent and fresh-process fence; explicit local confirmation resolves selected request; repeated fee sync imports zero |
| Actual pinned V3 synthetic SELL in another seeded lab account | Native import preserves captured output; API preflight diagnoses CSV overlap despite mismatched commission currency; zero added activities and balance stays0 |
| Unresolvable Yahoo symbol in a synthetic BUY batch | Native HTTP400 permits core's recognized-symbol retry; only resolvable FEE stored; incomplete readback cannot resolve intent; no cash write |
| Cleanup preflight over actual readback | Selects exactly3 manifest-owned canonical IDs, excludes opening/manual/foreign context, performs no DELETE |
| Partial import cancellation (2026-10-09) | First FEE committed; second independently blocked; timeout and fresh process remain fenced. Sole owned app stopped, its database work terminated, zero remaining database sessions verified before restart. Exact accepted subset unchanged, intent retained, no replay |
| Delayed cash completion (2026-10-09) | Native PUT waits in AccountBalance trigger; timeout, initial balance0 and fresh-process fence observed. Release commits42.42 once; matching balance does not clear cash intent |
| Delayed cash cancellation (2026-10-09) | Native PUT waits before84.84 upsert; independent owned app/DB quiescence cancels it. Restart balance remains0 and cash intent remains fenced |

The delayed case proves more than a response lost after commit: complete empty
readback is observed while a live INSERT is independently blocked. The controller
checks `pg_stat_activity` reports an advisory wait before release. The native
request then finishes once. Positive resolution does not dispatch another POST.
This does not prove cancellation for an absent/partial request in production,
replica/queue recovery, or resolution of an uncertain cash PUT.

The subsequent cancellation scenarios use the same unique isolated instance.
After observing an advisory-waiting request, the controller verifies the exact
Compose ownership, stops its sole app, and terminates remaining connections in
its disposable database, excluding the verifying connection and held barrier.
It verifies zero application work, releases/closes its own barrier, verifies zero
other database sessions, then restarts the sole app. This independent quiescence
proof is stronger than assuming a closed client socket cancelled SQL work.
Complete post-restart readback preserves the exact accepted subset or old cash.
No cancellation resolver is introduced: partial import and cash intents stay
pending even with this isolated proof. A matching balance after delayed completion
also leaves the fence intact. Production topology and an explicit reviewed
request-bound resolution procedure remain gates; none of these steps authorizes
stopping or terminating work in a shared service.

The first cash-barrier rehearsal failed because the controller saw Order before
all migrations had created AccountBalance. No scenario was accepted from that
attempt, and its resources were removed. Readiness now requires both tables.
The controller bounds the entire driver protocol to600 seconds, with incomplete
or oversized protocol lines rejected. Each barrier acquisition uses the same
buffered `select`/`os.read` protocol with its own30-second deadline; a partial line
cannot bypass that deadline. Invalid PID/acknowledgement, premature EOF and
oversized output fail without echoing process data. A failed acquisition reaps
its local subprocess before the controller tears down the owned lab.

The2026-10-09 rehearsal replayed every scenario above from a freshly built
rootless adapter image after the barrier correction. Both independent quiescence
proofs and the mapping-change rejection passed. The generated worker, Compose
containers/network, profile-fixture image and uniquely named adapter image were
removed afterward. The controller pins the generated Compose name with `-p`
and refuses optimized Python before Docker because its native evidence checks
require assertions enabled.

The CSV scenario now seeds output captured from the unchanged external V3
converter over a public synthetic statement. Only its target account ID changes.
[Pinned input/output and converter limits](v3-transition.md) distinguish this
actual synthetic conversion from a private historical statement conversion.
Its purpose is to prove that overlap cannot silently cause a second API import,
including when fee currency semantics differ. Actual backfill reconciliation and
adoption remain explicit operator gates. Free-text MANUAL fee
incompatibility is separately established in [fee-contract.md](fee-contract.md).

## Cleanup and rollback preflight

`scripts/cleanup_degiro.py` consumes a private complete activities JSON plus a
private YAML expected manifest containing source_account, target_account and
activities keyed by canonical broker comment. Each expected DTO has exactly the
10 canonical fields. It creates a new mode0600 proposal with exact created IDs
and a digest of the input snapshot; it refuses overwrite. Missing, changed,
duplicate, foreign-owned, redacted or unproved identities stop selection.

```sh
.venv/bin/python scripts/cleanup_degiro.py \
  --snapshot private-activities.json --manifest private-expected.yaml \
  --output private-cleanup-proposal.yaml
```

This offline utility has no HTTP/delete path and provides no deletion permission.
A later authorized executor would still need fresh exact readback, unchanged
ownership, bounded-ID confirmation and an independently tested rollback. Deleting
rows alone does not restore asset profiles/market data or cancel old requests.

Both native lab controllers use `scripts/lab_cleanup.py`. Before any Docker
mutation, it creates an operator-owned mode0600 YAML ownership record under the
mode0700 gitignored `tmp/lab-recovery/` directory. The record contains only the
UUID project and exact discovered container/network/image IDs. It never contains
the temporary Compose manifest, generated passwords, tokens or environment.
The private manifest is removed with its temporary directory even when cleanup
fails; recovery does not require it.

Cleanup independently attempts every local driver/barrier process, escalates a
10-second terminate timeout to kill and a bounded wait, then independently
handles containers, networks and fixture images. Each Docker command has a
30-second timeout. Container deletion precedes network/image deletion. Partial
Compose startup and a failed shutdown cannot skip later steps: cleanup uses
exact Docker IDs rather than `compose down`. Immediately before each removal,
it checks the full ID and the UUID project label; networks must also be internal.
Generated quote containers, the worker and profile-fixture image carry the same
project label. It never prunes the host, forces image deletion or deletes an
operator-supplied runtime image. A runtime image built separately remains the
caller's responsibility.

Catchable SIGTERM/SIGINT raise an exit through the same cleanup path; repeated
signals are ignored during bounded cleanup. A primary scenario failure remains
the primary exception, with a sanitized cleanup warning if recovery is incomplete.
A successful scenario with failed teardown exits unsuccessfully. The record is
removed only after all cleanup steps succeed. If the process is killed with
SIGKILL, the host crashes, Docker is unavailable or ownership checks fail,
cleanup is **not guaranteed**. Preserve the record and recover explicitly:

```sh
.venv/bin/python scripts/lab_cleanup.py \
  --recover tmp/lab-recovery/degiro-c13-<uuid>.yaml
```

The same command accepts an owned `degiro-interest-<uuid>.yaml` record. It refuses
public/symlinked/foreign-owner records or invalid project/ID shapes. It discovers
partially started resources by the recorded project label, saves their full IDs,
then rechecks each ID/label before removal. Changed/foreign resources are rejected
and the record survives. Do not edit the record to claim shared resources. If
Docker state changes concurrently, stop and inspect the owned project; never
substitute a name-only deletion or broad pruning. Local child PIDs are deliberately
not persisted because PID reuse makes delayed PID-based deletion unsafe.

Source rollback is a scoped Git revert. Preserve any actual financial uncertainty
journal; the lab ownership record has no authority over production or such journals.

## Remaining acceptance limits

The real reader still marks history completeness unverified. The saved real ledger
contains deliberately blocking Flatex interest/fund compensation. These findings
do not authorize excluding those rows, asserting an independent statement proof,
clearing cash/partial uncertainty or running live imports. Full real read-only
reconciliation and operator CSV transition remain separate evidence requirements;
production mutations/deployment retain Florent's explicit approval gate.
