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
