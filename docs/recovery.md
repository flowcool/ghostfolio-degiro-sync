# Durable write intent and explicit recovery

Live synchronization requires `STATE_DIR`: an existing persistent directory owned
by the process UID and mode0700. For a future container deployment this must be a
private writable persistent mount for UID10001, separate from its read-only app
and mapping. DRY_RUN needs no state mount. Missing/unsafe state stops live work
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
metadata. Import payloads are keyed by canonical broker comment and contain exact
activity financial fields; cash payloads contain target and amount. These are
private financial records, not credentials. Tokens, login data and OTP never enter
state. Lock/journal files are mode0600; symlinks, shared permissions and malformed
ownership/state are refused. Atomic replacement fsyncs file and directory before
dispatch. A crash anywhere after preparation preserves a conservative fence,
including a crash before HTTP actually starts.

Only exact complete synchronous acceptance confirms an import intent. Partial,
degraded, failed or lost responses retain it. A cash response failure also remains
pending. A later process refuses all writes while any intent is unresolved;
there is no automatic replay or clear-on-empty behavior. Confirmation retains the
1,000 most recent resolved-request metadata entries, ordered by their UTC
confirmation timestamps (request ID breaks ties). Older confirmed audit metadata
ages out; pending financial intent is never pruned. Journals over1MB still fail
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
broker login, token exchange, automatic replay or cash/partial cancellation.

Recovery is currently exercised in
offline regressions and the [disposable full-server delayed-result/restart
scenario](isolated-acceptance.md). Production completion/cancellation proof
remains separate.

## Operator preflight and local confirmation

Select the exact pending request ID from the private journal before beginning.
Provide `GHOST_HOST`, `GHOST_TOKEN`, `GHOST_ACCOUNT_ID`, `DEGIRO_ACCOUNT_ID` and
`STATE_DIR` from the established environment/secret pointer. The command does not
require broker credentials or a mapping file. Do not paste a bearer into its
arguments. Stop scheduled adapter work before operator recovery; its owner lock
also refuses overlap rather than waiting.

```sh
.venv/bin/python scripts/recover_degiro.py --expected-intent-id <selected-request-id>
```

The default verifies all expected activities and retains the pending journal.
Only a subsequent explicit invocation with `--confirm-local-state` confirms that
selected local intent, obtaining fresh evidence again. Neither mode sends a
financial mutation. The script ships at `/app/scripts/recover_degiro.py` in the
rootless image and can run against the same private persistent state mount under
the same UID. Its output contains counts and outcome only, not IDs, DTOs or tokens.
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
erase state or change namespace to force retry. The approved acceptance issue owns
that remaining procedure. Production service interruption/compensation requires
Florent's separate authorization.

## Rollback

Revert the scoped adapter/recovery commits before deployment. For an eventual
deployed uncertain request, stop its scheduler under operator authorization and
retain the private journal plus exact readback; reverting code does not undo
activities or cancel requests already running at the server. The disposable lab
owns its isolated reset/teardown. No live DELETE or broad cleanup is provided by
this recovery boundary.
