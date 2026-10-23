# Tasks

## 1. Private source archive

- [ ] 1.1 Deliver `scripts/archive_degiro_history.py` with the specified date/output interface, vault-only credentials, one bounded broker session, raw financial response retention, private keyed index and partial-failure behavior. Add synthetic regressions in `tests/test_history_archive.py` for boundary, preservation and retention scenarios. Update `docs/read-only.md` with the pinned-image invocation and archive limits. Verify with `.venv/bin/python -m pytest -q tests/test_history_archive.py`, the full offline suite, `bash scripts/check.sh`, core integrity, and a network-disabled pinned-image invocation using synthetic transport. Do not contact the real vault or broker as a test.

- [ ] 1.2 Add offline inspection to the archive script. Verify index/response hashes and produce a private row inventory with explicit legacy exclusions, malformed/unknown reasons, unassessed evidence and blocked import status. Add synthetic tests for row conservation, overlap boundaries, bad hashes, input preservation and zero network/write dispatch. Update `docs/read-only.md`. Verify with `.venv/bin/python -m pytest -q tests/test_history_archive.py -k exclusions` and the full required offline checks after this source change.

Real acquisition remains in the owning operation after source approval, implementation, review and publication. Bind the exact script commit/hash, image digest, 2000-01-01 through the broker-local current date, credential source, private output path and retention proof before the authorized real run. No task here weakens whole-account refusal or counts archive success as the two-instance qualification.
