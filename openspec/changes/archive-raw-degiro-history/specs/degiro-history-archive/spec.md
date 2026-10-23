# Spec Delta

## Purpose

Let an operator retain the requested DEGIRO history as private source evidence, including records that the financial importer cannot process.

## ADDED Requirements

### Requirement: Explicit bounded archive

The archive command SHALL accept explicit start and end dates, a window size from 2 through 366 days and a new output directory. It SHALL reject more than 120 overlapping windows before credential access. It SHALL require financial simulation mode. It SHALL use one vault credential retrieval and broker login per execution, sequential bounded requests, no retries and a bounded logout attempt. Direct broker credential variables SHALL remain rejected. It SHALL never contact Ghostfolio or submit financial changes.

#### Scenario: Invalid scope and bounded access

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k boundary` runs synthetic dates, credentials and HTTP
- **THEN** invalid scope stops before credential loading, one valid execution logs in once, requests stay in the existing broker read allowlist, and no order or Ghostfolio request occurs.

### Requirement: Preserve source evidence before interpretation

The archive SHALL retain each successful financial response before row interpretation. It SHALL preserve the original response body bytes and their SHA256, including original numeric text. It SHALL retain transactions and cash overview responses for every requested window, current account information and portfolio/cash updates, and available referenced product metadata. An explicitly requested statement SHALL retain its original UTF-8 CSV bytes. A private index SHALL bind each response to endpoint kind, requested dates, HTTP status, source account and fetch timestamps. It SHALL omit request URLs, headers and authentication responses. Detected credential fields SHALL cause refusal before that body is published.

Unsupported legacy rows, repeated id0 rows, unknown types, empty or malformed financial row shapes SHALL remain in their original successful response. The archive SHALL not merge, deduplicate, normalize, repair or silently remove them. An archive is not a synchronization snapshot or evidence of complete broker history.

#### Scenario: Legacy and malformed rows remain available

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k preservation` runs mixed supported, legacy, unknown, malformed and high-precision responses
- **THEN** every retained response matches its input bytes and hash, no row disappears, and request dates remain distinct from verified coverage.

### Requirement: Private retained partial output

The archive SHALL refuse pre-existing output, symlinks and input/output overlap before broker login. The output directory SHALL be mode 0700 and files mode 0600, owned by the executing user. It SHALL publish each response without replacement and update one private index atomically. The index SHALL distinguish pending, completed and failed collection. Completion SHALL mean only that all requested collection steps succeeded. Historical completeness SHALL remain unverified.

On failed HTTP, timeout, invalid encoding, credential-bearing body or storage failure, the command SHALL stop without retry, attempt logout, return nonzero and retain all previously published files. Logs SHALL contain only sanitized stages, counts and statuses. A later run SHALL require a new output directory; it SHALL not overwrite or resume the uncertain attempt.

#### Scenario: Failure preserves earlier evidence

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k retention` injects failures after successful windows
- **THEN** earlier bytes remain unchanged, partial status is explicit, authentication material stays absent, overwrite is refused, and no request is retried.

### Requirement: Archive grants no import permission

The archive SHALL be an explicitly mounted versioned script run with the pinned connector image. It SHALL add no normal-sync snapshot override or financial writer setting. The existing whole-account refusal, source freshness, supported accounting and historical-completeness guards SHALL remain unchanged. A raw archive SHALL not be accepted as a current-cash snapshot.

Baseline: `docs/read-only.md` describes the current normalized capture; `docs/source-contract.md` documents legacy-format refusal; `tests/test_degiro_sync.py` covers whole-account refusal. The archive is an added retention path, not a change to those contracts.

#### Scenario: Financial refusal remains effective

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py tests/test_degiro_sync.py -k 'archive or whole_account or unverified_history'` runs
- **THEN** archiving retains unsupported evidence while normal synchronization still refuses unsupported or unverified account data before writes.

### Requirement: Explicit offline exclusions

Offline archive inspection SHALL verify the index and response hashes without credentials or network access. Its private report SHALL retain a stable source reference for each locatable row using response identity and row offset. It SHALL report recognized unsupported legacy records as excluded, with reasons. It SHALL distinguish malformed, unknown and unassessed evidence from supported accounting. Unreadable envelopes SHALL receive an explicit response-level finding; missing rows or values SHALL not be invented.

Inspection SHALL not remove rows from the archive, merge overlap records, create a filtered synchronization input, or authorize a supposedly safe import subset. Unsupported or ambiguous required evidence SHALL keep the account's import status blocked. A row without a diagnostic SHALL not be described as valid or fully reconciled. The report SHALL explain that no financial write occurred and that full-account synchronization guards still apply.

#### Scenario: Exclusions are visible and imports remain blocked

- **WHEN** `.venv/bin/python -m pytest -q tests/test_history_archive.py -k exclusions` inspects a hashed archive with supported-looking, legacy, unknown and malformed inputs
- **THEN** every locatable row has one source-bound inventory result, exclusion reasons remain visible, all archive bytes stay unchanged, no credential or network is used, and no subset is made importable.
