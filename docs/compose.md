# Compose importer and reusable Ugreen lab

Florent approved this operating boundary on 2026-10-10: maintain the Compose
base here; infra installs and manages the persistent lab on Ugreen. The lab
keeps its data between runs and is used on demand. Production activation remains
separately authorized. No agentvm lab installation is part of this procedure.

## Importer for an existing Ghostfolio

`compose.yaml` follows IBKR's one-service-per-account, mapping mount, internal
Ghostfolio hostname and run-once/optional-supercronic pattern. It retains the
DEGIRO rootless image, read-only filesystem, dropped capabilities, private
persistent journal and reviewed URL policy. It does not install Ghostfolio.

Supply nonsecret settings through the infra configuration mechanism:

| Setting | Meaning |
| --- | --- |
| `DEGIRO_IMAGE` | Reviewed immutable runtime image digest selected by infra |
| `GHOST_NETWORK` | Existing Ghostfolio Docker network, with `ghostfolio` alias |
| `DEGIRO_ACCOUNT_ID`, `GHOST_ACCOUNT_ID` | Explicit source and destination identities |
| `DEGIRO_MAPPING_PATH` | Existing verified mapping file, mounted read-only |
| `DEGIRO_STATE_PATH` | Existing UID/GID10001 private0700 persistent directory |
| `DRY_RUN` | Defaults to1; changing it requires separate financial authority |
| `CRON` | Empty by default: run once. Five numeric fields enable scheduling |

`SYNC_MODE=rolling`, `LOOKBACK_DAYS=90`, `MAPPING_FILE` and `STATE_DIR` are fixed
inside the template. Inject `DEGIRO_USERNAME`, `DEGIRO_PASSWORD`,
`DEGIRO_TOTP_SECRET` and `GHOST_TOKEN` from the approved off-git SOPS/host loader.
Optional `APPRISE_URLS` is also protected environment input; `APPRISE_TIMEOUT`
defaults to10. Compose passes environment names; never commit values, put them
in a plaintext env file, print rendered secret-bearing Compose configuration,
or place them in command-line arguments.

The loader/recreation contract in [runtime.md](runtime.md) still applies.
`restart: "no"` avoids silently restarting with stale environment values.
Infra's supervisor must rerun the loader when recreating the container. An
explicit cron setting starts the scheduler; it does not run an immediate sync.
Use a separate run-once command for a reviewed initial DRY_RUN.

DEGIRO currently needs an already valid Ghostfolio bearer. Reusing IBKR's token
renewal is separate work and must be settled before permanent production cron.
Preparing or deploying the test lab does not authorize production imports.

## Persistent isolated lab

`compose.lab.yaml` defines a separate `ghostfolio-degiro-lab` project:

- Ghostfolio3.81.0, Postgres15-alpine and Redis7-alpine use the exact pinned
  versions/digests already used by the disposable DEGIRO lab.
- PostgreSQL has a project-owned named volume. Normal stop/restart retains it;
  do not run `down -v` or delete runs/state to reset a test.
- The Docker network is internal, with no production or proxy network attached.
  Ghostfolio exposes only `127.0.0.1:3334` by default (`LAB_UI_PORT` can change).
  There is no Traefik route or new public hostname.
- `lab-check` is an on-demand `tests` profile. It receives no broker credentials,
  production bearer, notifications or cron. Its only writable mount is `/runs`;
  inputs and scripts are read-only.

Build the fixture image with `docker build -f lab/Dockerfile -t LAB_IMAGE lab/`
through infra's approved image workflow. The image reuses the disposable lab's
exact quote/profile seam: native import/account/database code stays unchanged;
Yahoo profile lookup reads `/lab/profiles.json` instead of the network. The
profile file contains synthetic TEST and retained destination profile metadata.
Unknown symbols fail. This fixture is for import/recovery testing, not live
prices, market performance or production deployment.

Infra injects `LAB_POSTGRES_PASSWORD`, its matching `LAB_DATABASE_URL`,
`LAB_ACCESS_TOKEN_SALT` and `LAB_JWT_SECRET_KEY` through SOPS. Nonsecret settings
are `LAB_GHOST_IMAGE`, `DEGIRO_IMAGE`, `LAB_UI_PORT`, `LAB_PROFILES_PATH`,
`LAB_CAPTURES_PATH` and `LAB_RUNS_PATH`. Use dedicated Ugreen paths under the
existing `/volume1/docker` convention, separate from production. The project
name must remain `ghostfolio-degiro-lab` for the host guard.

Prepare captures before installation and make a private copy owned by UID10001
for the runner: directories0700, regular files0600, no hard links/symlinks.
Keep original evidence in its original location and verify copied hashes.
`LAB_PROFILES_PATH` is the copied bundle's `profiles.json`; the fixture server
must have read access. `LAB_RUNS_PATH` is an existing UID/GID10001 directory0700.
Do not make input files globally readable to solve permissions.

Health/readiness is the native `GET /api/v1/health`. Infra verifies readiness,
persistent storage and ownership before testing. For UI inspection:

```sh
ssh -N -L 3334:127.0.0.1:3334 ugreen
```

Then open `http://127.0.0.1:3334` locally. Infra supplies the usual SSH target.

## Prepare frozen real-capture replay

The development command below performs no HTTP or Docker action. Use the
retained90-day broker capture, complete destination capture and verified mapping
with their independently retained SHA256 values:

```sh
.venv/bin/python scripts/prepare_lab.py \
  --broker PRIVATE_BROKER.json --broker-sha256 BROKER_SHA256 \
  --destination PRIVATE_DESTINATION.json --destination-sha256 DESTINATION_SHA256 \
  --mapping PRIVATE_MAPPING.yaml --mapping-sha256 MAPPING_SHA256 \
  --output-directory NEW_PRIVATE_DIRECTORY
```

It runs the original complete-destination rolling preflight at the capture's
clock, copies source bytes unchanged, prepares offline asset profiles and pins
the expected activity plan in `manifest.yaml`. Retain its printed manifest
digest independently. Preparation refuses unsafe/changed files, output/input
aliases and overwrites. A partial directory after an I/O failure is unapproved;
choose a new output directory rather than overwriting it.

The real replay seeds only the captured target account in a new isolated test
user/account, preserving financial DTOs and mapping only the account ID. It
verifies exact native stored signatures, including the full captured target
history, before importing proposals. Other production accounts are not copied;
their ownership/conflicts have already been checked by original offline
preflight. No opening trades or historical evidence are invented. A native seed
rejection, duplicate collapse or signature difference fails the test and leaves
private evidence for diagnosis; it is not silently repaired.

## Invoke the persistent lab

Run on Ugreen from the reviewed checkout with infra's lab-only protected
environment. Retain the source tree because the Compose runner mounts its
script and public fixture. No real DEGIRO credentials are needed:

```sh
python3 scripts/run_compose_lab.py synthetic --manifest-sha256 MANIFEST_SHA256
python3 scripts/run_compose_lab.py replay --manifest-sha256 MANIFEST_SHA256
```

The host wrapper validates the exact Compose project/service, fixture image
marker, internal network, localhost publication and absence of foreign network
members. It then validates runner configuration before arming the command.
Do not bypass it with a direct `docker compose run lab-check`.

Each invocation creates a separate test user/account. Its ephemeral bearer stays
in memory, never in run files. `LAB_RUNS_PATH/<uuid>/run.yaml` records staged
ownership/provenance and final counts; `state/` retains the actual adapter
journal. Failed runs retain both, without automatically retrying, deleting test
data, stopping services or terminating DB sessions. Repeated invocations add
isolated test records; cleanup requires a separately reviewed exact ownership
manifest and explicit reset authorization.

The host imposes a ten-minute deadline. If it expires, it inspects the unique
worker name/UUID label and removes only that exact owned disposable worker ID.
Persistent services and data remain intact. Failed worker-ownership checks leave
it for explicit recovery and print only its safe generated name. Stopping the
worker does not prove cancellation of an in-flight Ghostfolio request; preserve
the uncertain journal and investigate exact readback before further work.

The synthetic scenario reuses opening10/SELL2/dividend/fee evidence, checks
DRY_RUN zero writes, exact native imports/cash, a lost acknowledgement followed
by positive readback recovery, preserved opening rows and a repeat with zero
new imports. The real scenario imports the previously pinned proposal, verifies
cash and preserved seed rows, then repeats without new activities. Its clock is
the saved broker capture's `fetched_at`: this is frozen replay, not a fresh
DEGIRO read or a production-ready plan. Historical basis/completeness stay
unverified.

The existing [disposable acceptance](isolated-acceptance.md) still owns tests
that delay database INSERTs, stop the app or prove cancellation. Never attach
`scripts/isolated_acceptance.py` to this persistent infra-owned stack.

## Rollback and ownership

Source rollback is an atomic revert of the Compose/lab implementation commit.
Infra owns image builds/publication, Ugreen install, secret provisioning,
controlled service stop and restoration of the prior image/config. Preserve the
database volume, captures and private runs/journals. Image/code rollback neither
undoes imported records nor cancels requests. Lab reset and production financial
recovery are separate explicit actions. The production importer and lab templates
are independent; installing the latter must not change the existing Ghostfolio
stack or activate its scheduler.
