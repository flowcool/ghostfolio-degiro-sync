---
description: Python conventions for the DEGIRO adapter and immutable Ghostfolio core
globs: ["*.py"]
---

- Package modules use strict type hints. Validate external inputs before constructing records. Legacy code keeps its style until extraction. Never rewrite generated core bytes.
- Logging: `log.warning` for operational skips, `log.error` for failures, `log.debug` for verbose
- Never log a token or credential
- Errors: `raise RuntimeError(...)` with explicit message, never silent `return` on failure
- Core/adapter split: `ghostfolio_degiro_sync` owns broker logic; `ghostfolio_core.py` is the immutable byte projection of pinned IBKR broker-agnostic functions. Never hand-edit the guarded core. Checker/tests/cleanup use the defining package modules. Do not refactor the canonical sibling.
- Tests: `pytest` in `tests/` (offline, pure functions, requests mocked; dev-only deps in `requirements-dev.txt`, never in the image). Run `.venv/bin/python -m pytest -q` before commit. A logic change ships with a test; real-data checks require explicit operator authorization outside pytest
- Business operations stay module-level functions. Classes are limited to frozen dataclasses and TypedDict data records. Secrets use repr=False.
