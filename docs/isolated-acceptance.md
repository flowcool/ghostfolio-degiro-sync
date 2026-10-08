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

## Observed results (2026-10-08)

| Scenario | Exact observed result |
| --- | --- |
| Seeded opening BUY10 TEST/USD | Native account contains one opening row before adapter work |
| Adapter DRY_RUN | Proposes3 rows; stored count remains1; balance remains0 |
| First adapter import | Native SELL2, paid DIVIDEND and FEE preserve all10 canonical DTO fields; net holding8; current balance12.30EUR |
| Repeated full sync | No proposed/imported rows; stored count remains4 |
| Uncertain delayed INSERT | PostgreSQL BEFORE INSERT trigger blocks owned FEE999 on an advisory lock; HTTP times out; complete GET still contains only4 rows |
| New Python process before release | Reads persisted intent and refuses synchronization; empty pending readback refuses resolution; no replay |
| Release owned barrier | Native original request inserts exactly one row; complete count5; exact positive readback resolves stored intent; repeated fee sync imports zero |
| CSV-shaped unmarked SELL in another seeded lab account | API preflight diagnoses manual/CSV overlap; zero added activities and balance stays0 |
| Unresolvable Yahoo symbol in a synthetic BUY batch | Native HTTP400 permits core's recognized-symbol retry; only resolvable FEE stored; incomplete readback cannot resolve intent; no cash write |
| Cleanup preflight over actual readback | Selects exactly3 manifest-owned canonical IDs, excludes opening/manual/foreign context, performs no DELETE |

The delayed case proves more than a response lost after commit: complete empty
readback is observed while a live INSERT is independently blocked. The controller
checks `pg_stat_activity` reports an advisory wait before release. The native
request then finishes once. Positive resolution does not dispatch another POST.
This does not prove cancellation for an absent/partial request in production,
replica/queue recovery, or resolution of an uncertain cash PUT.

The CSV scenario uses the accepted DTO shape of an unmarked trade, not an actual
run of the external V3 converter over a private statement. Its purpose is to prove
that such overlap cannot silently cause a second API import. Actual backfill
reconciliation/adoption remains an explicit operator gate. Free-text MANUAL fee
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

Controller teardown removes only its UUID-named worker and its own Compose
project containers/network. No host bindings or production service stops are
used. If interrupted, identify the owned `degiro-c13-<uuid>` project by its Compose
labels before cleanup; never issue broad Docker pruning. A source-code rollback
uses Git revert and retains any actual uncertain journal.

## Remaining acceptance limits

The real reader still marks history completeness unverified. The saved real ledger
contains deliberately blocking Flatex interest/fund compensation. These findings
do not authorize excluding those rows, asserting an independent statement proof,
clearing cash/partial uncertainty or running live imports. Full real read-only
reconciliation and operator CSV transition remain separate evidence requirements;
production mutations/deployment retain Florent's explicit approval gate.
