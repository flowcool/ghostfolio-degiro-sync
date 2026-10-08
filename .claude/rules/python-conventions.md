---
description: Python conventions for the DEGIRO adapter and immutable Ghostfolio core
globs: ["*.py"]
---

- No type hints — match existing style
- Logging: `log.warning` for operational skips, `log.error` for failures, `log.debug` for verbose
- Never log a token or credential
- Errors: `raise RuntimeError(...)` with explicit message, never silent `return` on failure
- Option C (Florent, 2026-10-08): `degiro_to_ghostfolio.py` owns broker logic; `ghostfolio_core.py` is the immutable byte projection of pinned IBKR broker-agnostic functions. Never hand-edit the guarded core. Checker/tests/cleanup keep their utility boundaries; no shared package or sibling refactor.
- Tests: `pytest` in `tests/` (offline, pure functions, requests mocked; dev-only deps in `requirements-dev.txt`, never in the image). Run `.venv/bin/python -m pytest -q` before commit. A logic change ships with a test; live-data checks stay in `/test-sync` and the review-pr A/B dry run
- No classes — functional style with module-level functions
