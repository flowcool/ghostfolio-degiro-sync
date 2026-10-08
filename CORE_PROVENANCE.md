# Ghostfolio core provenance and propagation

This document is the single authoritative provenance record. The YAML block is
read by the checker; do not maintain a second pin in a workflow or generated file.
The selected function list below defines the maintained broker-agnostic boundary.
The source pin tracks the reviewed v2.2.0 release. This project never modifies
the IBKR sibling; propagation remains explicit and human-controlled.

```yaml
format: 1
repository: https://github.com/flowcool/ghostfolio-ibkr-sync.git
commit: 54958ab1035eb97a1f67f9072b79699813ec3800
source_path: ibkr_to_ghostfolio.py
source_sha256: 9717927fd7102401359dcdc44c6080da5211aac298afa1442dbf17e36cf15096
imports:
  - import logging
  - import re
  - from datetime import datetime, timezone
  - from math import isfinite
  - import requests
constants:
  - log
  - _UNRESOLVED_SYMBOL_RE
functions:
  - ghost_headers
  - activity_date_is_current
  - activity_is_active
  - ghost_get_accounts
  - ghost_find_account_id
  - parse_unresolved_symbol
  - accepted_import_subset
  - mark_import_uncertain
  - ghost_import_activities
  - ghost_update_cash_balance
```

## Byte identity contract

`ghostfolio_core.py` is the deterministic projection of the pinned Git blob.
AST identifies top-level units; original byte slices preserve signatures, bodies,
comments and line endings. Units are sorted by source position and joined with
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
2. Update `commit` to the full reviewed SHA and `source_sha256` to the SHA256 of
   `git show <new-sha>:ibkr_to_ghostfolio.py`. Review additions/removals in the
   lists if dependencies or the broker-agnostic boundary changed.
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
   Florent's authorization; push/PR publication also requires authorization.
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
