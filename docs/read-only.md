# Read-only broker capture

Use the Docker Compose setup from the root README. A read-only command authenticates to the configured vault, retrieves the DEGIRO login/TOTP secret, logs into the broker once, captures the requested data and attempts logout. It does not contact Ghostfolio or place/cancel orders.

```sh
docker compose run --rm degiro-sync --read-only \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD --output /state/capture.json
```

Replace dates and use a new filename every time. Optional `--report-country fr --report-language fr` requests a statement; select the actual account locale. Captures are financial data, written as private mode 0600 files and never overwritten. Keep them outside Git.

The public command uses the pinned container image and environment configured through Compose. Never enable raw connector logging, print authentication responses or export the entire vault for troubleshooting. Capture success does not prove history completeness; unknown categories and ambiguous relationships still block financial synchronization.

## Private source archive

The normalized command above can refuse legacy accounting before saving a snapshot.
To retain source evidence, mount the versioned `scripts/archive_degiro_history.py`
into the pinned connector image. This separate command does not use the normal
accounting checks. It never creates importable synchronization input.

From your Compose checkout, create an `archive.compose.yaml` override:

```yaml
services:
  degiro-sync:
    mem_limit: 1g
    environment:
      DRY_RUN: "1"
      CRON: ""
    volumes:
      - type: bind
        source: ./scripts/archive_degiro_history.py
        target: /archive/archive_degiro_history.py
        read_only: true
        bind: {create_host_path: false}
```

Keep the configured vault environment and private state mount from the root setup.
The state directory must be writable by UID/GID 10001. Use a new output directory
under that mount for every attempt. Run the script once:

```sh
DEGIRO_IMAGE=ghcr.io/flowcool/ghostfolio-degiro-sync@sha256:4827041d92004d567f008a395e2e1ca9822cffa50d143cdd25cebe66ca233840 \
  docker compose -f compose.yaml -f archive.compose.yaml run --rm --no-deps \
  degiro-sync python /archive/archive_degiro_history.py \
  --from-date 2000-01-01 --to-date YYYY-MM-DD --window-days 90 \
  --output-directory /state/history-UNIQUE
```

Replace the end date with the account-local current date. Record the script commit
and SHA256, image digest, dates, window size, memory limit and private output path
before a real acquisition. The script stays outside the runtime image. The example
pins the runtime dependency set; it does not certify complete history.
Optional `--report-country fr --report-language fr` adds the original UTF-8 statement
CSV. Supply both options with the actual account locale.

The script uses one vault retrieval and one broker login. It collects transactions
and cash overview for overlapping windows, current account information and updates,
and referenced product metadata. It attempts logout on success and failure. Requests
use the connector's bounded read allowlist. There are no retries or Ghostfolio calls.
Direct broker credential variables remain forbidden.

`index.yaml` binds each response to its kind, requested dates where applicable, source
account, fetch times, HTTP status, byte count and SHA256. The keyed `steps` record
contains durable request intents. Successful financial bodies are HTTP-decoded bytes,
with numeric text, repeated rows, legacy types and malformed rows unchanged. The
archive does not merge overlapping windows or certify their coverage. Directory mode
is 0700; file mode is 0600. Authentication, discovery and logout bodies are excluded.
Keep the archive outside Git and preserve it after failure.

Limits: 2–366 days per window, at most 120 windows, 16 MiB per decoded body,
512 MiB retained bodies, 10000 distinct valid product IDs and 100 product requests.
Each product request contains at most 100 IDs. Invalid product IDs are counted as
skipped metadata references after source publication; their source rows remain.
The existing transport buffers a response before the decoded-size check. These
limits do **not** bound downloaded bytes or peak memory. Keep an explicit container
memory limit. A killed process can leave a pending intent or an unindexed staging
or response file. Preserve those files; do not resume into the same directory.

Invalid encoding, unparseable JSON, nesting beyond 64 containers, credential keys or
credential material, oversized responses, HTTP errors and storage failures stop the
command with a nonzero exit. Unsafe bodies are not published. Available status, size,
hash and refusal reason remain in the index when storage permits. Earlier durable
responses remain. Credential checks inspect duplicate JSON keys and all decoded
strings; CSV checks conservatively reject authentication vocabulary and known login
values. Such checks can refuse otherwise readable evidence. No refused body is
claimed as retained.

`pending` means collection is unfinished. `failed` means a step or logout failed.
`requests_finished` means only that all requested steps returned successfully.
A crash can leave `pending` even after a response was published. Every archive keeps
`history_completeness_verified: false` and `import_status: archive_not_importable`.
The normal whole-account refusal and current-cash guards still apply. Retaining
unsupported data grants no permission to import other rows or convert history.

## Offline archive inspection

Use the same mounted script and pinned image to inspect an archive. Mount source
archives read-only when possible. Record the SHA256 of `index.yaml` before inspection;
pass that exact value as `--index-sha256`. A hash binds the report to those bytes.
It does not authenticate broker history or establish complete coverage.

```sh
DEGIRO_IMAGE=ghcr.io/flowcool/ghostfolio-degiro-sync@sha256:4827041d92004d567f008a395e2e1ca9822cffa50d143cdd25cebe66ca233840 \
  docker compose -f compose.yaml -f archive.compose.yaml run --rm --no-deps \
  degiro-sync python /archive/archive_degiro_history.py \
  --inspect-directory /state/history-UNIQUE --index-sha256 INDEX_SHA256 \
  --output-directory /state/inspection-UNIQUE
```

Inspection does not load credentials or use the network. Do not supply acquisition
dates, windows or locale options in inspection mode. Use a new output directory
outside the archive. The report is `report.yaml`, mode 0600 in a mode 0700 directory.
Source files and their bytes stay unchanged. Existing destinations, overlapping
input/output paths, symlinks and hardlinks are refused. Input directories must be
owned by the executing user and mode 0700. Indexed files must be owned regular files
with mode 0600 and one link. Response basenames must match their response identifier.
The index is limited to 2 MiB; the archive's body and total byte limits still apply.

The report binds each response to its identifier, kind, requested dates when present,
size and hash. `verification: hash_verified` only describes byte integrity. It does
not describe accounting validity. `available_sha256` records an index claim before
verification; it is not a verified hash. Every locatable row contributes once to
one classification:

- `excluded_legacy`: `CASH_FUND_NAV_CHANGE` or `CASH_FUND_TRANSACTION`.
- `malformed`: a row is not an object, has an invalid discriminator or duplicate
  keys, or a CSV record has a different column count from its header.
- `unknown`: the source type is not recognized.
- `unassessed`: a recognized source category or metadata row has not received
  accounting validation. No row is certified valid or fully reconciled.

History types use `buysell` for transactions and `type` for cash movements. The
inspection checks shape and discriminators, not financial fields or relationships.
Per-response type counts and classification counts conserve locatable rows.
`rows` records zero-based JSON Pointer offsets, such as `/data/cashMovements/3`.
Product keys use JSON Pointer escaping. CSV records use `/csv/0` for the first data
record after the header, plus the physical line where that record ends. Metadata
rows cover product entries, account information and top-level update collections;
nested attribute cells are not counted as separate financial rows.

Overlapping windows remain separate observations. Pending intents, refused bodies,
unreadable responses, ambiguous collection keys and missing collections have explicit
findings. A response without a readable, unambiguous collection has no invented rows.
Unindexed files, including staging files, are listed but never opened or adopted.
The report does not merge records, remove exclusions or create an import subset.

Exit 0 means the report was published, including when it contains findings.
`inspection_status: findings_detected` requires reading those findings.
`unassessed_only` also grants no accounting approval. Invalid index integrity or
unsafe source/destination prevents report publication and returns nonzero. Every
report keeps `history_completeness_verified: false`, `financial_writes: 0` and
`import_status: archive_not_importable`. Full-account synchronization guards remain.
