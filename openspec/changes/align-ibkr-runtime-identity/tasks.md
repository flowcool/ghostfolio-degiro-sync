# Tasks

Implementation starts after operator approval of this change. Keep one implementation owner and use this checklist for its slices. Stable publication remains a separate authorized release.

## 1. Automatic release identity

- [ ] 1.1 Derive target version and full revision from checked Git release metadata. Pass them through Dockerfile, scripts/release_image.py and .github/workflows/release-image.yml. Extend scripts/verify_release_image.py and existing release checks to enforce runtime/OCI agreement on both architectures. Update README build guidance. Cover release-publication requirements Automatic build identity and Immutable candidate and stable channels. Verify with `.venv/bin/python -m pytest -q tests/test_release_image.py tests/test_verify_release_image.py` and `.venv/bin/python scripts/smoke_container.py "$IMAGE"` against an isolated synthetic release build. Invalid or contradictory metadata must refuse publication.

## 2. Startup presentation

- [ ] 2.1 Add the fixed banner and version/commit line in entrypoint.sh and ghostfolio_degiro_sync/app.py. Keep arbitrary command execution, isolated worker silence, notification behavior and exit codes. Update the runtime checks and README examples required by degiro-synchronization requirements Consistent runtime software identity and Fixed Docker startup banner. Verify `.venv/bin/python -m pytest -q tests/test_foundation_runtime.py tests/test_notify.py tests/test_failure_diagnostics.py` and `.venv/bin/python scripts/smoke_container.py "$IMAGE"`. Check default, explicit-option and cron invocations without broker credentials or financial writes.

## 3. Exact candidate promotion

- [ ] 3.1 Add the versioned promotion helper and adapt .github/workflows/release-image.yml to sign new candidates with a pinned build-time Cosign action and copy the highest qualified RC index for stable. Validate the bounded qualification record, signature, native digests, source and identity before any write. Preserve v-prefixed channels, occupied-version guards and uncertain-write stops. Update README release guidance. Cover release-publication requirements Qualified candidate promotion and Immutable candidate and stable channels. Verify `.venv/bin/python scripts/promote_release_image.py --plan` with synthetic events and read-only stub responses for the stated acceptance and refusal cases; retain the responses and observed output. Replay existing release checks. No stable publication is authorized by this task.
