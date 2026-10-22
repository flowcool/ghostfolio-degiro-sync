# Ghostfolio core provenance and propagation

This document is the single authoritative provenance record. The YAML block is
read by the checker; do not maintain a second pin in a workflow or generated file.
The selected function list below defines the maintained broker-agnostic boundary.
The source pin tracks the reviewed IBKR v3.0.0 commit below. This project never modifies
the IBKR sibling; propagation remains explicit and human-controlled.

```yaml
format: 2
repository: https://github.com/flowcool/ghostfolio-ibkr-sync.git
commit: 403b4ccf13dcce076c2dc4c08633905c96c1a898
sources:
- path: ghostfolio_ibkr_sync/ghostfolio.py
  sha256: 68013f405dc9f00a994034b1cbde355287211fc7bfc04b31260ed1d44b599f2c
- path: ghostfolio_ibkr_sync/ibkr.py
  sha256: f4478c2cce928abf232e57ba26cb0725dfeb69dd79d301574c954808b8fcb4ce
imports:
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: import json
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: import logging
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: import re
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: from collections.abc import Mapping
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: from datetime import UTC, datetime
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: from math import isfinite
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: from typing import Any
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: import requests
constants:
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: log
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: Config
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: GHOST_REDIRECT_ERROR
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: _UNRESOLVED_SYMBOL_RE
functions:
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_headers
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_response_is_redirect
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: activity_date_is_current
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: activity_is_active
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_get_accounts
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_find_account_id
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: parse_unresolved_symbol
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: accepted_import_subset
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: mark_import_uncertain
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_import_activities
- source: ghostfolio_ibkr_sync/ghostfolio.py
  name: ghost_update_cash_balance
- source: ghostfolio_ibkr_sync/ibkr.py
  name: log_lab_evidence
```

## Byte identity contract

`ghostfolio_core.py` is the deterministic projection of the pinned Git blobs.
Format 1 remains readable for historical verification. Format 2 records complete
source-file SHA256 hashes and source-qualified units. The checker rejects name
collisions and unresolved globals or lazy annotations before writing any output.
AST identifies top-level units; original byte slices preserve signatures, bodies,
comments and line endings. Format 2 orders imports, assignments, then functions. Each group follows the
declared source order and each source file's line order. Units are joined with
exactly two LF bytes. There is no generated header or reformatted code. The whole
file must equal the reconstructed projection, not merely a stored local hash.
The original logging setup/config/broker code is excluded; adapter logging is its
own responsibility. The core functions treat activity comments as opaque strings.

Broker indexes (`ghost_get_existing_orders`), conversions, mapping helpers with
broker-facing defaults, minor-unit activation, holdings/manual matching, broker
comment keys and cleanup matching remain outside this file. URL validation and
uncertain-import/currency/freshness orchestration live in the adapter. Do not
change core functions to implement these policies.

## Verify locally (no sibling writes or network)

```sh
.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main
.venv/bin/python -m pytest -q
```

The local main check uses the checkout's `refs/heads/main`; it does not claim the
remote was refreshed. CI clones canonical main into a disposable bare repository,
fetches the pin and independently checks both the bytes and current main SHA.
Any local byte divergence fails. A different main SHA emits a visible GitHub
warning and job summary requesting human review, with no automatic propagation.
A missing canonical commit/ref or network failure fails the check. CI has read-only
permissions and runs weekly as well as on PR, push and manual dispatch.

## Human-controlled propagation

1. In a scratch checkout of the canonical IBKR repository, inspect the proposed
   commit and the diff of selected functions and dependency units. Do not fetch,
   checkout or modify the frozen production sibling for this procedure.
2. Update `commit` to the full reviewed SHA. Record the SHA256 of the complete
   bytes returned by `git show <new-sha>:<source-path>` for each ordered source.
   Review source-qualified units if dependencies or the maintained boundary change.
3. Explicitly regenerate using that scratch checkout:

   ```sh
   .venv/bin/python scripts/check_core.py --source /path/to/scratch/ibkr --write --check-main
   .venv/bin/python scripts/check_core.py --source /path/to/scratch/ibkr --check-main
   .venv/bin/python -m pytest -q
   git diff --check
   git diff --numstat
   git diff -- CORE_PROVENANCE.md ghostfolio_core.py
   ```

4. Review tests and adapter assumptions affected by the source changes. Commit the
   pin, generated artifact and any required regression tests together only with
   explicit authorization; push/PR publication also requires authorization.
   Missing/renamed units fail rather than silently falling back. Never hand-edit
   the guarded core or infer approval from a main-advance warning.

Before an authorized commit, restore the previous provenance and generated core
from the same verified scratch backup. After an authorized commit, use
`git revert <exact-propagation-commit>` to restore them atomically. No runtime or
financial rollback is performed by this tool.

If IBKR later exposes the identical standalone core file, replace projection with
whole-file byte/hash comparison in a separately approved migration. No extraction
or refactor in IBKR is part of this implementation.

## Attribution

Copied source remains subject to the sibling LICENSE (MIT NON-AI, copyright
2026 porana contributors), retained unchanged in this repository. Original
source and this provenance record must accompany distributed substantial copies.
