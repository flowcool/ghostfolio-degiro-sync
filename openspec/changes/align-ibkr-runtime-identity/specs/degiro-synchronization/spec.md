# Spec Delta

## ADDED Requirements

### Requirement: Consistent runtime software identity

New release images SHALL report `ghostfolio-degiro-sync version X.Y.Z — commit <prefix>` at connector container startup and at every normal application invocation. The prefix SHALL be the first twelve lowercase hexadecimal characters of the embedded full commit. One-off, explicit connector options and CRON cycles SHALL report the same identity before configuration failure or broker access. Local builds without metadata SHALL use `dev` and `unknown`.

The isolated notification worker SHALL remain silent and SHALL NOT emit startup identity. An explicit arbitrary command passed to the Docker entrypoint SHALL keep its current command and exit behavior. Identity reporting SHALL use no network lookup, Docker socket or operator version setting. Existing logging streams, severity, failure notification count, scheduler behavior and exit status SHALL remain unchanged.

Baseline changed: `entrypoint.sh` currently emits APP_VERSION only on its default path; `app.main` has no software-identity line. Existing regressions are in `tests/test_foundation_runtime.py`, `tests/test_notify.py` and `tests/test_failure_diagnostics.py`.

#### Scenario: Identity across execution modes

- **WHEN** `.venv/bin/python -m pytest -q tests/test_foundation_runtime.py tests/test_notify.py tests/test_failure_diagnostics.py` runs synthetic release and local startup cases
- **THEN** one-off, explicit connector options and scheduled application cycles show the same version and commit prefix, missing configuration still shows identity, the notification worker stays silent, and exit/notification contracts pass.

### Requirement: Fixed Docker startup banner

The Docker entrypoint SHALL print a fixed ASCII `DEGIRO SYNC` banner and a `DEGIRO -> Ghostfolio` subtitle once per connector container start. The dynamic identity SHALL follow the banner. Default one-off, CRON and explicit connector-option startup SHALL show the banner. Individual scheduled cycles SHALL print identity without repeating the banner.

The banner SHALL require no new setting, runtime renderer, terminal escape code or external request. Arbitrary command execution SHALL keep its current behavior.

Baseline changed: `entrypoint.sh` has no banner. The sibling entrypoint provides a static literal; its broker name SHALL be adapted.

#### Scenario: Banner in installed startup

- **WHEN** `.venv/bin/python scripts/smoke_container.py "$IMAGE"` runs against the isolated candidate image
- **THEN** connector startup shows one banner followed by the identity in one-off and scheduled modes, scheduled cycles do not repeat the banner, and the existing fail-closed smoke passes without credentials or network.
