# Prospective synchronization from a verified cutover

Prospective mode preserves existing Ghostfolio history and synchronizes eligible
operations after a verified cutover. It does not certify historical accounting,
cost basis, fees, performance or tax reporting. Publishing this mode does not
amend real-account acceptance or authorize production activation.

## Opening evidence

A private version1 YAML manifest binds one DEGIRO account, one Ghostfolio account,
a precise aware cutover instant, the verified ISIN-to-Yahoo mapping and two private
JSON captures through SHA256 digests. `CUTOVER_SHA256` separately pins the manifest:
changing either the manifest or an attachment requires explicit revalidation.
Files must be owned regular mode0600 files, without final symlinks or hard links,
and each attachment is bounded to2MB. Original captures are never overwritten.

The broker capture contains the normal raw snapshot, including every held stock's
product metadata. The destination capture contains `account`, the complete
`activities` response and `captured_at`. Destination capture occurs inside the
broker fetch interval; the cutover equals that broker capture's `fetched_at`.
The interval must last at most five minutes and contain no source executions,
cash events or target activities dated after its start. The operator must avoid
trading or editing the target during baseline establishment. A concurrent event,
missing bridge or mismatch is a refusal, not a repair suggestion.

Opening source holdings must equal quantities derived from destination history
by verified instrument mapping. Only the existing STOCK/contract-size1/currency
contract is supported. Missing products, ambiguous mappings, incompatible units,
short positions and unknown instruments block. Opening broker cash must independently
pass the existing EUR/zero-pending-settlement checks and equal destination cash.
The baseline records existing inventory; it creates no opening BUY or cash flow.
Only `basis_status: unverified` is currently supported. Accurate historical basis
requires separate evidence and scope; this mode never reconstructs it.

## Capture and preparation

The host-side read-only capture utility uses existing credential environment and
URL/transport policies. It requires `DRY_RUN=1`, reads the previous and current
broker-local dates, retrieves all held product metadata, obtains account/activities
GETs within the broker read interval, and logs out. It sends no financial POST,
PUT or DELETE to Ghostfolio. DEGIRO authentication/logout retain their existing
bounded protocol. Do not inspect credentials or raw HTTP errors.

```sh
.venv/bin/python scripts/capture_cutover.py \
  --output-directory tmp/private-cutover
```

The output directory must be new; partial captures after a failure remain
unapproved evidence. The command prints attachment digests only. Capture alone
neither verifies opening agreement nor activates synchronization. Pin the verified
mapping file's digest using `sha256sum`, then prepare the manifest offline:

```sh
.venv/bin/python scripts/prepare_cutover.py \
  --broker tmp/private-cutover/broker.json \
  --broker-sha256 "$BROKER_SHA256" \
  --destination tmp/private-cutover/destination.json \
  --destination-sha256 "$DESTINATION_SHA256" \
  --mapping "$MAPPING_FILE" --mapping-sha256 "$MAPPING_SHA256" \
  --source-account "$DEGIRO_ACCOUNT_ID" --target-account "$GHOST_ACCOUNT_ID" \
  --output tmp/private-cutover/manifest.yaml
```

Preparation validates opening agreement before exclusive mode0600 publication.
It refuses overwrites, existing input/output aliases and invalid evidence; it
prints `CUTOVER_SHA256`. Keep the private directory and attachments available at
the same bound paths. Utilities run from the host development environment; the
runtime image continues shipping only runtime/recovery code.

## Explicit DRY_RUN

Configure the normal verified mapping, environment-only credentials and target
URL, plus:

```sh
export SYNC_MODE=prospective
export CUTOVER_MANIFEST=/absolute/private/path/manifest.yaml
export CUTOVER_SHA256=the_verified_manifest_digest
export DRY_RUN=1
```

Provide an existing owned mode0700 `STATE_DIR`, including for prospective DRY_RUN.
The account lock covers reads and dispatch, and an unresolved durable import or
cash intent blocks prospective verification. Run the existing command:

```sh
.venv/bin/python degiro_to_ghostfolio.py --sync
```

Prospective mode always rereads the complete interval from the opening capture's
start date through the current Europe/Zurich broker-local date. A requested recent
`--from-date` or cron lookback cannot shorten it. Windows retain their existing
one-day overlap, identity conflict checks and request budget. There is no mutable
coverage checkpoint to advance after partial work; full replay deliberately trades
extra bounded reads for simpler continuity. Exceeding the request budget refuses
processing rather than silently losing an outage interval.

Each run requires exact raw cash-statement multiset agreement, including dates,
minutes, value dates, ISINs, descriptions, currencies, amounts and order references.
CSV corroborates the scoped cash feed; it supplies neither event identity nor a
payment/tax relationship. Stable source identities retain distinct same-minute
events. Every execution needs exactly one matching signed execution-cash row and
every execution-cash row needs a source execution. Ambiguous or discrepant totals
block without new cent tolerances. Existing fee, dividend and yield contracts
still classify and validate all relevant prospective events.

Eligible source events are strictly after the cutover. Events at or before it
must match the unchanged opening prefix exactly, excluding only derived cash
`balance`. A late, amended or removed prefix event invalidates the baseline.
Future events, activity timestamps finer than Ghostfolio milliseconds, and cash
events whose value date crosses the cutover or fresh capture boundary are refused. Unknown financial categories, transfers and
corporate actions still block; this feature does not implement them.

Protected destination rows must retain their exact IDs and canonical financial
signatures. New, missing or changed legacy rows block. Every existing target row
after cutover must match an eligible canonical source activity; manual/CSV overlap
is not adopted through financial coincidence. Other-account ownership and
canonical identity conflicts retain their existing refusal behavior.

Opening quantities plus the entire prospective trade ledger must equal fresh
broker holdings. Only already accepted destination inventory funds pending sales.
Current cash remains a fresh separately validated snapshot, never an old opening
balance substituted for today's cash. Complete account preflight precedes every
financial write.

A successful prospective command exits0 and explicitly states that historical
completeness and basis remain unverified. Its result separately reports
`prospective_verified`, `history_verified`, `cutover` and `basis_status`; it never
sets historical completeness true to pass the old write gate. It proposes eligible
activities, accepts none and invokes neither financial transport in DRY_RUN.
Missing/changed evidence, incomplete coverage or uncertainty exits1 with a bounded
status. `SYNC_MODE=full_history` remains the default and retains its original gate.

## Review, activation and rollback

Offline tests exercise manifest integrity, opening agreement, boundary/coverage
refusals, exact plans, input preservation, first/repeated runs, uncertainty and the
actual configuration/command path. The existing owned Ghostfolio lab exercises
native acceptance and recovery with public synthetic broker evidence. Neither
proves that a real account's opening contract is valid. Real-account evidence
belongs to acceptance issue infra-8tt.56.11; production activation and rollout
remain in infra-8tt.56.12 and require Florent's separate authorization.

Required CI and completed CodeRabbit review must cover the exact implementation
head before integration. Production scheduling, credentials, network and image
publication use the existing infrastructure handoff boundary. This runbook does
not authorize setting `DRY_RUN=0` on a production account.

Before implementation/lab changes, verify the baseline Git blob and owned cleanup
access. Revert the exact prospective implementation commit(s) to undo code changes;
retain private manifests and uncertainty journals. Stop an authorized schedule
before code rollback, through its approved infrastructure procedure. Code rollback
does not delete already created financial activities, restore cash or cancel
requests; any such recovery needs fresh exact-ID evidence and separate approval.
The existing disposable lab controller removes only its recorded UUID-owned
containers, internal network and fixture image. Never prune shared Docker state.
