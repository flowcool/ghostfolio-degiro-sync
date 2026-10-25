# Durable write intent and explicit recovery

The installed package keeps persistence, locks and recovery in `journal.py`.
`sync.py` owns execution and coverage. Recovery, cutover and cleanup commands
use their owning modules. The private journal schema and command options remain
unchanged during this extraction. Every write still records durable intent
before dispatch; an uncertain result keeps the cash and retry fences active.

Live synchronization requires `STATE_DIR`: an existing persistent directory owned
by the process UID and mode 0700. For the supported Compose deployment, follow the
[README mount preparation](../README.md#vault-and-mapping), separate from the
read-only app and mapping. Full-history DRY_RUN requires no application journal,
but the state bind-mount source directory must still exist to start the Compose
service, as defined in the README. Prospective and rolling DRY_RUN require the
private state directory. Missing/unsafe state stops live work
before broker login. Deleting state, replacing it with tmpfs or changing the
configured origin can discard recovery evidence; none is a recovery procedure.
Keep origin/source/target stable and retain the directory in backups.

The adapter hashes the exact approved origin and destination into the account
filenames, and records source ownership inside the journal. Changing broker source
cannot create an independent lock for the same destination or replace its owner.
Its exclusive nonblocking file lock covers live source/target
reads and dispatch. Separate invocations using the same directory cannot overlap.
All independent instances targeting that account must share this state; a local
file lock is not a distributed lock across different volumes or machines.

The keyed YAML journal contains ownership, one pending intent and resolved-request
metadata. Rolling mode additionally stores successful coverage only after full live success, never after DRY_RUN or partial work; see [the rolling contract](prospective-sync.md). Import payloads are keyed by canonical broker comment and contain exact
activity financial fields; cash payloads contain target and amount. These are
private financial records, not credentials. Tokens, login data and OTP never enter
state. Lock/journal files are mode 0600; symlinks, shared permissions and malformed
ownership/state are refused. Atomic replacement fsyncs file and directory before
dispatch. A crash anywhere after preparation preserves a conservative fence,
including a crash before HTTP actually starts.

Only exact complete synchronous acceptance confirms an import intent. Partial,
degraded, failed or lost responses retain it. A cash response failure also remains
pending. A later process refuses all writes while any intent is unresolved. Rolling mode may automatically confirm an import only after complete exact unique positive readback; its DRY_RUN verifies without clearing state. There is no automatic replay or clear-on-empty behavior, and uncertain cash remains fenced. Confirmation retains the
1,000 most recent resolved-request metadata entries, ordered by their UTC
confirmation timestamps (request ID breaks ties). Older confirmed audit metadata
ages out; pending financial intent is never pruned. Journals over 1MB still fail
closed rather than truncating financial evidence. No operator compaction command
is provided.

## Explicit positive import readback

`resolve_import_intent(config, existing_body, expected_intent_id=...)` is an operator/helper boundary,
not an automatic CLI retry. It performs no HTTP or financial mutation. Under the
same lock it requires a complete unredacted current activity snapshot and proves
every pending canonical identity exists exactly once in the configured target,
with unchanged symbol, source, UTC instant and all financial fields. Foreign
ownership, changed mapping, redaction, malformed counts, duplicate rows and
partial/empty evidence refuse resolution. A confirmed response resolves only
that stored request; normal fresh preflight still gates later synchronization.
The expected request ID is mandatory and checked against the pending intent under
the same owner lock. Select it before obtaining readback and retain it throughout
recovery; do not substitute whichever ID is pending afterward. A stale request ID
cannot resolve a successor, even when its activity payload is identical. This
selection guard does not authenticate a saved snapshot or prove its freshness.

Never supply a fabricated or stale snapshot to release a financial gate.
`readback_import_intent` and the operator command below obtain fresh authenticated
account and complete activity GETs from the approved origin while holding the
same owner lock. Transport is forced into GET-only mode, even if the normal sync
configuration enables writes. Wrong account, excluded/redacted context, malformed
or incomplete readback and changed request ID refuse confirmation. There is no
broker login, automatic replay or cash/partial cancellation. Security Token
mode permits one Ghostfolio login POST before the financial GET-only readback.

Recovery is currently exercised in
offline regressions and the [disposable full-server delayed-result/restart
scenario](https://github.com/flowcool/ghostfolio-degiro-sync/blob/15d595f/docs/isolated-acceptance.md), recorded before the contributor lab was removed. Production completion/cancellation proof
remains separate.

## Operator preflight and local confirmation

Select the exact pending request ID from the private journal before beginning.
Provide `GHOST_HOST`, exactly one of `GHOST_ACCESS_TOKEN` or legacy `GHOST_TOKEN`,
`GHOST_ACCOUNT_ID`, `DEGIRO_ACCOUNT_ID` and `STATE_DIR` from the established
environment/secret pointer. The command does not require broker credentials or
a mapping file. The same [auth contract](ghostfolio-auth.md) applies; a
wrong/missing pending intent fails before login. Do not paste either credential into its
arguments. Stop scheduled adapter work before operator recovery; its owner lock
also refuses overlap rather than waiting.

```sh
.venv/bin/python scripts/recover_degiro.py --expected-intent-id <selected-request-id>
```

The default verifies all expected activities and retains the pending journal.
Successful preview and confirmation print `snapshot SHA-256=<digest>` alongside
the exact matched count and local-state action. This is the SHA-256 of the
complete activities readback used by that invocation, computed by the adapter
without publishing the rows, account IDs, token or request payload. Retain it
with the selected request and command evidence when documenting recovery. A
later invocation may have a different digest because unrelated activities changed;
each invocation obtains and verifies fresh GET evidence under the account lock.
The digest is an audit reference, not a substitute for exact ownership/financial
matching, independent quiescence, statement completeness or recovery approval.
A failed verification emits no success digest.

Only a subsequent explicit invocation with `--confirm-local-state` confirms that
selected local intent, obtaining fresh evidence again. Neither mode sends a
financial mutation. The script ships at `/app/scripts/recover_degiro.py` in the
rootless image and can run against the same private persistent state mount under
the same UID. Its output contains counts, outcome and a snapshot digest, not IDs, DTOs or tokens.
Transport and JSON errors return failure without private details. A persistence
failure requires inspection of the journal; do not assume the state replacement
did or did not complete after a filesystem failure.

Positive confirmation means only that this import's exact identities are present.
It does not verify history, unsupported source categories or current cash for the
next synchronization. Complete normal preflight still applies. Cash and partial
intents remain fenced and require the separately proved operator procedure.

Cash intents have no automatic resolver. Matching current balance alone cannot
prove the old PUT finished or was independently cancelled. Partial/absent import
results likewise require independent completion/cancellation evidence; do not
erase state or change namespace to force retry. [ADR-0009](adr/0009-uncertain-result-recovery-boundary.md) records this boundary.
Production service interruption or financial compensation requires separate
operator authorization.

## Rollback

Revert the scoped adapter/recovery commits before deployment. For an eventual
deployed uncertain request, stop its scheduler under operator authorization and
retain the private journal plus exact readback; reverting code does not undo
activities or cancel requests already running at the server. The disposable lab
owns its isolated reset/teardown. No live DELETE or broad cleanup is provided by
this recovery boundary.

## Cleanup and rollback preflight

`scripts/cleanup_degiro.py` consumes a private complete activities JSON plus a
private YAML expected manifest containing source_account, target_account and
activities keyed by canonical broker comment. Each expected DTO has exactly the
10 canonical fields. It creates a new mode 0600 proposal with exact created IDs
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

Accepted import evidence remains separate from the submitted batch. A valid short
response records only proven creations in the pending intent's `accepted` list.
This list never proves that omitted rows were not created. The intent stays
pending, no later sell batch or cash update runs, and automatic replay remains
blocked. Exact full positive readback is still required to settle the request.
A changed legacy/v1 spelling is not an exact pending-request readback.

A MANUAL profile may return a UUID in place of its requested symbol. The adapter
associates it only with the same source identity, account, timestamp, type, exact
quantity/price/fee/currency and MANUAL data source. The generated core first proves
the created row and profile. The adapter keeps the requested source identity and
stores the returned UUID with an exact financial fingerprint in the private
journal. Subsequent complete reads use unchanged source evidence or that durable
association. Unknown or conflicting associations stop the account. Zero fees and
zero interest remain valid evidence. Simulation can inspect an association but
cannot certify it in the journal or advance coverage.

## Historical identity preview

The maintenance command stays outside the runtime image. It never runs from
CRON. Preview reads saved files only. It does not load credentials or honor an
inherited live mode:

```sh
.venv/bin/python scripts/migrate_degiro_identity.py preview --inputs /private/inputs.yaml --output /private/new-review
```

Use schema `degiro-migration-inputs-v1` in keyed YAML. Supply `tool_commit` as
an exact 40-character source commit, `clock` as an aware fixed ISO timestamp,
`inventory_complete: true`, and `accounts` keyed by each configured numeric
source account. Each account value is the saved Ghostfolio target account.
`mapping` references a YAML file containing `symbols` (ISIN to symbol) and
`quote_currencies` (symbol to currency). File references have `path` (relative
to inputs) and `sha256`. `reports` keys each saved DEGIRO source snapshot with
its `source_account`; `replay_order` lists every report key exactly once.
Source snapshots need actual `from_date`/`to_date` and the original financial
JSON in `_diagnostic_wire`, as acquired by the private read command. Missing
exact source evidence leaves rows unproven. Do not recreate wire decimals from
rounded payloads.

`snapshot` references a complete Ghostfolio activity response and declares
`complete: true`, `unredacted: true`, exact `count`, `capture_ref`,
`captured_at`, `destination_version` and `destination_image` (`sha256:...`).
Every row needs its ID, comment (including null), exact quantity/price/fee,
account/currency, date/type, `isDraft`, tags and profile context. Acquisition
of real source/destination evidence retains its own authority.

The new private directory contains deterministic `manifest.yaml` and its
SHA256. It inventories every activity ID, including inactive and old history.
Rows have one decision and a reason. Eligible rows require unique ownership,
exact source association and unchanged complete runtime selection, holdings
and failure behavior under the fixed clock. Missing proof removes replacements.
Inputs remain byte-identical; duplicate YAML keys, aliases, incomplete snapshots,
symlinks and output overlap are rejected. The manifest binds input, mapping,
implementation and destination hashes. Source windows do not prove lifetime
broker coverage. Target DTO, zero/MANUAL/UUID, background effects, pacing,
source lifetime and reversal qualifications remain explicit pending gates.
Preview does not authorize conversion, database restore or old-binary restart.

## Approved historical comment conversion

`apply` is a separate financial operation. Neither `DRY_RUN=0` nor a preview
approves it. Supply the reviewed input/manifest hashes, a separately approved
keyed YAML permit and a new private journal path:

```sh
.venv/bin/python scripts/migrate_degiro_identity.py apply --inputs /private/inputs.yaml --manifest /private/review/manifest.yaml --manifest-sha256 "$MANIFEST_SHA256" --approval /private/approval.yaml --approval-sha256 "$APPROVAL_SHA256" --journal /private/operation.yaml --host "$GHOST_HOST"
```

Permit schema is `degiro-migration-approval-v1`; authorization is
`apply-reviewed-comments`. Bind `host`, `manifest_sha256`, `owner_id`,
`destination_version` and `destination_image`. Maintenance accepts semantic
Ghostfolio versions at or above **3.86.0**, without an exact-version or upstream
commit pin. A prerelease of 3.86.0 is below the minimum; build metadata does not
change precedence. Record the actual version from the running application,
not the Docker tag `latest`. A permit may record `target_source_commit` for
provenance; it does not select an accepted upstream commit.
The original UpdateOrderDto allowlist review used Ghostfolio 3.86.0 source
[`ef47c0d`](https://github.com/ghostfolio/ghostfolio/tree/ef47c0d1b2c48fa4e97fb381561b514e657928cf).
Source inspection does not qualify any real target. The controller can reconnect
profiles and the service can queue background market-data work. Every class
(`TYPE:DATA_SOURCE`) in `qualifications` therefore needs `pass` and nonempty
`source_refs` for `source_identity`, `target_dto`, `manual_zero_uuid`,
`background_effects`, `pacing` and `reversal`, bound to that exact image.
Pending or failed classes block the operation. Keep their rows intact.

The operation must record `operation_plan_ref`, recoverable `backup_ref`,
`writer_exclusion_ref`, independent `settlement_ref`, `writers_stopped: true`,
`requests_settled: true`, exact `write_count`, measured positive `batch_size`
and nonnegative `pause_seconds`. `state_dir` must be the normal connector's
private state directory. Stop all competing writers and bind the actual deployed
image/version before approval. The engine holds normal destination locks and
refuses an unresolved normal sync intent. This does not replace external writer
exclusion or current deployment proof.

Credentials follow the existing exclusive `GHOST_TOKEN`/`GHOST_ACCESS_TOKEN`
policy and exact `GHOST_HOST`. Exchange happens once, after local approval and
lock checks. The dedicated transport permits only complete activities GET and
reviewed activity PUT. Scheduled sync gains no historical PUT route. DTOs use
stored activity currency and actual profile identity, explicit fields and exact
numeric JSON tokens. Numbers the target cannot preserve are refused. The engine
never copies the entire GET row into a PUT.

A private YAML journal persists and flushes each pending request before dispatch.
Complete readback must preserve every field and every protected row except the
approved comment. A failed request, normalization, profile effect or uncertain
completion stops further writes. Confirmed subsets and pending requests remain
in the journal. No automatic retry is permitted, even if readback still shows
the original comment: a delayed request may complete later. Independent
completion/cancellation evidence is required for recovery. Retain captures and
journal; leave writers stopped at this boundary.

## Inspect and reverse a stopped conversion

Inspection reads saved complete snapshots and the private journal only:

```sh
.venv/bin/python scripts/migrate_degiro_identity.py inspect --journal /private/operation.yaml --manifest /private/review/manifest.yaml --manifest-sha256 "$MANIFEST_SHA256" --snapshot /private/current.json --snapshot-sha256 "$SNAPSHOT_SHA256"
```

Each journal-owned ID is `original`, `converted`, `changed` or `absent`.
An unresolved apply or reversal request adds `uncertain:`. Observation does not
settle a request. Inspection writes nothing and reads no credentials.

Reversal uses the same bounded transport, private locks, pending intent and
complete readback. It restores comments only. Its separate permit uses the
same schema and exact target/class prerequisites as apply, with authorization
`rollback-reviewed-comments`, current `journal_sha256`, exact reversal
`write_count` and the operation's approved recovery scope:

```sh
.venv/bin/python scripts/migrate_degiro_identity.py rollback --journal /private/operation.yaml --manifest /private/review/manifest.yaml --manifest-sha256 "$MANIFEST_SHA256" --approval /private/rollback.yaml --approval-sha256 "$ROLLBACK_APPROVAL_SHA256" --host "$GHOST_HOST"
```

For every pending request, `settlements` must key the activity ID with
`direction` (`apply` or `rollback`), `outcome` (`completed` or `cancelled`),
`independent: true` and an independent `evidence_ref`. The saved disposition must
agree with exact fresh readback. An unchanged original comment alone is not
cancellation proof. A lost reversal response remains pending; do not repeat it.
Manual edits or any changed financial/profile context block reversal.
New v1 imports are outside the journal and remain untouched. Protected rows are
checked before and after every reversal.

Before resuming imports, retain the exact mixed-history DRY_RUN preview and
prove unchanged full source selection and zero duplicate creations under the
operation. Reversal does not start writers. Safe halt uses the exact qualified
candidate digest with `DRY_RUN=1` and the existing Compose target. If it cannot
start, keep writers stopped until compatible repair. Neither comment reversal
nor a source Git revert qualifies an older binary when retained v1 rows exist.
A database restore has a separate operation boundary and is never automatic.
