# Bounded synchronization and prospective acceptance

## Approved rolling operating contract

Florent confirmed this contract on 2026-10-10. Set `SYNC_MODE=rolling` for
normal operation: retrieve the 90 calendar days ending on the current
Europe/Zurich date (`today - 89 days` through today, inclusive). `LOOKBACK_DAYS`
remains 90. An explicit earlier `--from-date` supports catch-up; `--to-date`
must still be today. Internal request windows overlap by one day and retain
identity, conflict and budget checks. This policy replaces full cutover replay
for normal operation; the original prospective mode below remains available
for its independently verified acceptance evidence.

The first rolling run also proposes missing operations before service began.
Run `DRY_RUN=1` first and review proposals. It imports nothing and changes
neither cash nor coverage. Production financial writes and deployment still
require separate explicit authorization. No opening BUY, invented cash flow,
or historical-basis certification is introduced.

Existing exact canonical identities are skipped; changed financial content
is refused. Florent explicitly approved the existing IBKR manual-entry rules:
BUY/SELL entries of the same account, symbol and side may match within two
calendar days when quantity differs by less than 0.001; the closest match is
consumed once. Nearby entries with different quantities refuse processing.
Existing dividends of the same account and symbol within three days are
considered already represented, as in IBKR. These are duplicate-avoidance
heuristics, not proof of historical prices, fees or taxes. Other categories
retain their existing explicit reconciliation requirements. Existing rows are
never updated automatically.

The complete destination inventory plus pending trade quantities must equal
fresh broker holdings. Every existing canonical DEGIRO row within the requested
window must also exist with the same financial signature in the source plan.
Statement coverage, source execution/cash associations, independent current
broker cash, units and mapping remain mandatory. History completeness and
basis remain unverified; a successful rolling command reports that distinction.

The account-owned private YAML journal records coverage only after a complete
successful live run, including cash confirmation. A requested interval starting
after the last successful coverage date is refused before writes: use an
explicit earlier `--from-date` to cover the gap. First use without saved coverage
requires the initial DRY_RUN review; it cannot infer older missing history.
Partial failures and DRY_RUN never advance coverage. Persist `STATE_DIR` across
container replacement; losing it also loses the outage reference.

On restart, read Ghostfolio under the account lock. An interrupted import is
cleared automatically only after every intended activity is present exactly
once with matching canonical financial values. DRY_RUN may verify this but
preserves the pending journal. Missing, partial, changed, foreign or duplicated
results remain blocked because a delayed insertion may still arrive. An
uncertain cash write remains blocked and needs explicit recovery. No blind
resubmission, deletion or financial correction is performed.

Failure notifications reuse the IBKR isolated Apprise worker implementation
from sibling commit `2404fbd030ed4570da9b8e287205f06316399ec1`, outside the immutable core.
`APPRISE_URLS` is a JSON list (at most 10 destinations); `APPRISE_TIMEOUT` is
1–30 seconds, default 10. Empty configuration disables delivery. One alert is
attempted for each completed failed live synchronization. Success, warnings,
DRY_RUN, read-only capture and interrupted processes remain silent. Messages
contain fixed reason/action codes and UTC time, never account identifiers,
financial amounts, arbitrary exceptions or destination secrets. The worker
receives destination URLs on stdin, excludes broker/Ghostfolio credentials,
discards output and has one process-wide deadline. It never retries; delivery
failure does not change the sync result. Apprise configuration/deployment uses
the existing infrastructure handoff; no live notification is sent by tests.

Rollback: revert the exact rolling implementation commit and restore the prior
configuration. Preserve journals and captures; code rollback neither cancels
in-flight requests nor reverses already imported activities or cash updates.
Older binaries reject the extended journal containing `coverage`; preserve it
and use a forward fix or explicitly reviewed state migration rather than deleting
`STATE_DIR` to make an older version run.

## Prospective synchronization from a verified cutover

Prospective mode preserves existing Ghostfolio history and synchronizes eligible
operations after a verified cutover. It does not certify historical accounting,
cost basis, fees, performance or tax reporting. Florent approved prospective
real-account acceptance on2026-10-10: fresh opening captures must agree on
holdings, and broker cash must pass independent validation, followed by an actual prospective DRY_RUN with
zero financial writes. C13 and CSV-transition/recovery preflight evidence remain
required. This acceptance scope does not authorize production activation.

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
Capture/cutover clocks and eligible source events must include explicit seconds
and a timezone offset; minute-only timestamps are refused. The interval must
last at most five minutes and contain no source executions,
cash events or target activities dated after its start. The operator must avoid
trading or editing the target during baseline establishment. A concurrent event,
missing bridge or mismatch is a refusal, not a repair suggestion.

Opening source holdings must equal quantities derived from destination history
by verified instrument mapping. Only the existing STOCK/contract-size1/currency
contract is supported. Missing products, ambiguous mappings, incompatible units,
short positions and unknown instruments block. Opening broker cash must independently
pass the existing EUR/zero-pending-settlement checks. Destination cash may be
stale because the operator does not maintain it manually; an opening cash
difference does not block validation. DRY_RUN displays the independently verified
broker balance proposed for Ghostfolio and sends no balance update. Florent
approved this behavior on2026-10-10. Actual updates retain separate production authority.
The baseline records existing inventory; it creates no opening BUY or cash flow.
Only `basis_status: unverified` is currently supported. Accurate historical basis
requires separate evidence and scope; this mode never reconstructs it.
Legacy trade currencies and prices are preserved through protected signatures,
not certified against current quote metadata. They do not establish opening
inventory: exact current broker quantities and verified mapping do. New
prospective activities still require verified quote currencies and units.

## Capture and preparation

Use the normal verified mapping, credentials and target configuration with
`DRY_RUN=1`. One host-side command captures both accounts, checks their opening
agreement and publishes a private manifest:

```sh
.venv/bin/python scripts/prepare_cutover.py --capture \
  --output-directory tmp/private-cutover
```

Capture defaults to yesterday through today. If DEGIRO refuses a statement for
an empty interval, use `--from-date YYYY-MM-DD` to include a recent known cash
event. The observed2026-10-09/10 empty period returned HTTP500, while2026-10-03/10
returned a statement exactly corroborating one cash movement. This selects the
evidence interval; it does not change the cutover instant. Subsequent DRY_RUNs
replay the manifest's entire interval, including its protected opening prefix.

The directory must be new. The command uses existing read-only broker operations
and Ghostfolio account/activities GETs, then logs out. It sends no financial writes
and does not activate synchronization. On success it prints `CUTOVER_SHA256`;
on failure, retained files remain unapproved evidence. Keep the directory at the
same path. The mapping input must be mode0600, like the private captures.

Existing captures can also be validated offline with `prepare_cutover.py`:
provide `--broker`, `--destination`, `--mapping` and each corresponding
`--NAME-sha256`, plus `--source-account`, `--target-account` and `--output`.
Preparation refuses overwrites and input/output aliases. The utility runs from
the host development environment and is not included in the runtime image.

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

Each run requires raw cash-statement multiset agreement, with exact dates,
minutes, value dates, ISINs, descriptions, currencies and order references. Amounts
are exact except for the execution rounding explicitly approved by Florent
on2026-10-10: a unique STOCK execution with contract size1 and a supported
cent-valued currency may corroborate an API/CSV difference of at most0.01.
Both cent-valued cash views and the declared execution total must remain within
0.01 of one another and of signed unrounded quantity times price; the execution
total itself may retain subcent precision. Exact matches take priority, and
missing, duplicated or ambiguous candidates still refuse verification. Other
categories retain exact amount checks. CSV corroborates the scoped cash feed; it
supplies neither event identity nor a payment/tax relationship. Stable source identities retain distinct same-minute
events. Every execution needs exactly one matching signed execution-cash row and
every execution-cash row needs a source execution. Ambiguous or discrepant totals
outside that corroborated rounding bound block. Existing fee, dividend and yield contracts
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
