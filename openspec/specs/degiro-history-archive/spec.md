# degiro-history-archive Specification

## Purpose
Let an operator retain the requested DEGIRO history as private source evidence, including records that the financial importer cannot process.

## Requirements

### Requirement: Explicit bounded archive

The archive command SHALL accept explicit start and end dates, a window size from 2 through 366 days and a new output directory. It SHALL reject more than 120 overlapping windows before credential access. It SHALL require financial simulation mode using the existing simulation parser. It SHALL use one vault credential retrieval and broker login per execution, sequential bounded requests, no retries and a bounded logout attempt. Direct broker credential variables SHALL remain rejected. It SHALL never contact Ghostfolio or submit financial changes.

#### Scenario: Invalid scope and bounded access

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k boundary` runs synthetic dates, credentials and HTTP
- **THEN** invalid scope stops before credential loading, one valid execution logs in once, requests stay in the existing broker read allowlist, and no order or Ghostfolio request occurs.

### Requirement: Preserve source evidence before interpretation

The archive SHALL retain each eligible successful financial response before row interpretation. Retained bytes SHALL be the HTTP-decoded response body, not compressed network bytes. It SHALL preserve those bytes and their SHA256, including original numeric text. It SHALL retain transactions and cash overview responses for every requested window, current account information and portfolio/cash updates, and available referenced product metadata. An explicitly requested statement SHALL retain its original UTF-8 CSV bytes. A private index SHALL bind each response to endpoint kind, requested dates, HTTP status, source account and fetch timestamps. It SHALL omit request URLs, headers and authentication responses. JSON bodies SHALL be valid UTF-8 and parseable, with duplicate-aware key inspection and bounded nesting. Credential-key checks SHALL use the existing snapshot-redaction vocabulary. CSV SHALL pass UTF-8 and credential-material checks. Authentication values SHALL never be retained. Unparseable, invalid-encoding, credential-bearing or oversized bodies SHALL not be published. The index SHALL record the step, HTTP status if available, available byte count/hash and refusal reason, without the body.

Unsupported legacy rows, repeated id0 rows, unknown types and malformed row shapes inside eligible parseable responses SHALL remain in their original response. Readable envelopes with missing or empty collections SHALL remain available. This preservation guarantee SHALL NOT cover unparseable or otherwise refused bodies. The archive SHALL not merge, deduplicate, normalize, repair or silently remove them. An archive is not a synchronization snapshot or evidence of complete broker history.

#### Scenario: Legacy and malformed rows remain available

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k preservation` runs mixed supported, legacy, unknown, malformed and high-precision responses
- **THEN** every retained response matches its input bytes and hash, no row disappears, and request dates remain distinct from verified coverage.

### Requirement: Private retained partial output

The archive SHALL refuse pre-existing output, symlinks and input/output overlap before broker login. The output directory SHALL be mode 0700 and files mode 0600, owned by the executing user. It SHALL publish each response without replacement from an exclusively created private staging file, fsync the file and containing directory, and update one private index atomically with durable intent before dispatch. Each collection intent SHALL bind exactly one response. Archive/storage failures SHALL remain visible even if a vendor action catches their exceptions. The index SHALL distinguish pending, requests_finished and failed collection. requests_finished SHALL mean only that all requested collection steps succeeded. The index and inspection report SHALL always contain history_completeness_verified: false and import_status: archive_not_importable.

On failed HTTP, timeout, invalid encoding, credential-bearing body or storage failure, the command SHALL stop without retry, attempt logout, return nonzero and retain all previously published files. Logs SHALL contain only sanitized stages, counts and statuses. A later run SHALL require a new output directory; it SHALL not overwrite or resume the uncertain attempt.

#### Scenario: Failure preserves earlier evidence

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k retention` injects failures after successful windows
- **THEN** earlier bytes remain unchanged, partial status is explicit, authentication material stays absent, overwrite is refused, and no request is retried; crash points produce detectable pending entries or orphan files rather than accepted complete evidence.

### Requirement: Bounded retention and metadata collection

Each decoded body SHALL be limited to 16 MiB before publication. Retained response bodies SHALL total at most 512 MiB. The command SHALL limit distinct valid referenced product IDs to 10000 and product metadata requests to 100. It SHALL stop with retained partial evidence when a limit is exceeded. It SHALL clear inherited diagnostic body accumulation after each request. Product identifier extraction SHALL run only after source publication; invalid identifiers SHALL be reported without discarding their source rows or generating metadata requests for them.

The operation SHALL pin window size and a container memory limit. Existing buffered transport can allocate a response before its decoded-size check; documentation SHALL disclose this limit and SHALL NOT claim a bounded download. It SHALL NOT override the existing transport boundary to hide that limitation.

#### Scenario: Oversized or excessive input stops retention

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k limits` exercises oversized bodies, cumulative size, invalid product IDs and excessive product requests
- **THEN** unsafe bodies are unpublished, prior evidence survives, metadata requests stay bounded and diagnostic bodies do not accumulate across requests.

### Requirement: Archive grants no import permission

The archive SHALL be an explicitly mounted versioned script run with the pinned connector image. It SHALL add no normal-sync snapshot override or financial writer setting. The existing whole-account refusal, source freshness, supported accounting and historical-completeness guards SHALL remain unchanged. A raw archive SHALL not be accepted as a current-cash snapshot.

Baseline: `docs/read-only.md` describes the current normalized capture; `docs/source-contract.md` documents legacy-format refusal; `tests/test_degiro_sync.py` covers whole-account refusal. The archive is an added retention path, not a change to those contracts.

#### Scenario: Financial refusal remains effective

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py tests/test_degiro_sync.py -k 'archive or whole_account or unverified_history'` runs
- **THEN** archiving retains unsupported evidence while normal synchronization still refuses unsupported or unverified account data before writes.

### Requirement: Explicit offline exclusions

Offline archive inspection SHALL verify the index and response hashes without credentials or network access. Inspection SHALL treat the index as untrusted: response paths MUST be basenames without traversal; files MUST be private regular files without symlinks or hardlinks, with matching size and hash. It SHALL report pending intents and unindexed files without adopting them. Its private report SHALL give per-response row/type counts and stable response/offset references for flagged rows. Each locatable row SHALL contribute once to a closed classification count: excluded_legacy, malformed, unknown or unassessed. Overlapping windows remain separate observations. It SHALL report recognized unsupported legacy records as excluded, with reasons. It SHALL distinguish malformed, unknown and unassessed evidence from supported accounting. Refused/unreadable responses SHALL receive an explicit index-level finding; their unavailable bodies SHALL not be invented. Inspection SHALL not call the normal accounting-format check or history merger.

Inspection SHALL not remove rows from the archive, merge overlap records, create a filtered synchronization input, or authorize a supposedly safe import subset. Every archive SHALL have import_status: archive_not_importable, including archives without exclusion findings. Normal synchronization SHALL retain its whole-account guards for unsupported or ambiguous required evidence. A row without a diagnostic SHALL not be described as valid or fully reconciled. The report SHALL explain that no financial write occurred and that full-account synchronization guards still apply.

#### Scenario: Exclusions are visible and imports remain blocked

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k exclusions` inspects a hashed archive with supported-looking, legacy, unknown and malformed inputs
- **THEN** per-response classification counts conserve every locatable row and flagged rows have exact source references, exclusion reasons remain visible, all archive bytes stay unchanged, no credential or network is used, and no subset is made importable.
