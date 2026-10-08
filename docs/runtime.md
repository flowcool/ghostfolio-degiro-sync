# Rootless run-once and cron runtime

The image follows the IBKR Python 3.12 + supercronic harness. Its Python base is
pinned by multi-platform digest in `Dockerfile`; supercronic v0.2.49 has separate
official binary SHA256 pins for amd64/arm64. Only `requirements.txt` is installed,
with the complete direct/transitive dependency closure. Dev pytest/pip-audit,
optional connector QR/quotecast packages, Git state and private snapshots do not
ship. `.dockerignore` allowlists the build inputs and COPY lists runtime files.

The app runs as UID/GID10001. Its files remain owned by root, and the crontab is
created in the container's writable temporary directory. Read-only root filesystem
operation with a `/tmp` tmpfs is supported. `DRY_RUN=1` is the image default;
changing that environment value does not establish history proof or production
authorization. No image publication, deployment or production smoke is performed
by the validation workflow.

## Build and isolated validation

On a native amd64 host:

```sh
docker build --build-arg TARGETARCH=amd64 --build-arg APP_VERSION=local \
  -t ghostfolio-degiro-sync:local .
python3 scripts/smoke_container.py ghostfolio-degiro-sync:local
```

Native arm64 uses `TARGETARCH=arm64`. CI builds/tests on native Ubuntu amd64 and
arm64 runners; it does not install privileged emulation on agentvm. The smoke
driver uses disposable containers with no network, credentials or bind mounts,
read-only filesystems, bounded tmpfs, no capabilities and no-new-privileges.
It checks actual runtime UID/packages/core bytes, connector source parity, the
complete app file set, the real default run-once path, cron injection rejection,
and an actual minute cron invocation. Missing configuration must fail closed
before authentication; the scheduler must remain running and report that failed
job. This is a harness smoke, not a successful broker synchronization canary.

## Runtime operation boundary

Supply the environment and a read-only mapping file using the off-git SOPS
pointer and [synchronization configuration](synchronization.md). The temporary
Bitwarden-derived DEGIRO store/loader is described in [read-only.md](read-only.md);
it supplies broker environment variables without a plaintext env file. Ghostfolio
bearer provisioning is separate. Never pass secret values as command-line
arguments or print a Docker inspection containing the environment. An eventual
production Compose/runtime-secret setup belongs to the authorized infra rollout.

Without `CRON`, the entrypoint runs `--sync` once. With `CRON`, exactly five
numeric schedule fields are accepted and supercronic validates them. Named
shortcuts and embedded commands/newlines are rejected. Only the fixed sync command
is written to the crontab; no environment-provided command is evaluated.
Supercronic retains its default non-overlapping scheduling for this single job.
Independent instances targeting the same account still require operator control.

Default sync dates are today's UTC date and the previous89 days inclusive.
`LOOKBACK_DAYS` defaults to90 and accepts2..366. This operational window is based
on observed bounded history requests, not proof of completeness or an all-time
backfill. The overlapping fetch chunks are still used. A late local-day execution
can fall into the next UTC-day run; the lookback preserves coverage across runs.
Explicit `--from-date`/`--to-date` remain available for operator diagnostics.
Read-only snapshot mode still requires both dates and an output path.

Passing a command after the image name executes that command instead of the sync
entrypoint path, useful for isolated checks; it does not bypass the Python write
gates when invoking the adapter. Do not schedule arbitrary operator commands via
`CRON`.

## Connector provenance and propagation

`docs/connector-provenance.yaml` records the source commit, wheel hash, version,
module count and deterministic Python-tree digest. The3.0.36 wheel's84 Python
modules were compared byte-for-byte with the already inspected source clone.
The tree digest hashes sorted `degiro_connector/<relative-path>` UTF-8 names,
NUL separators and original file bytes, then a NUL separator after each module.
The container smoke reconstructs that digest from installed files on both
architectures. Version equality alone is insufficient evidence of source parity.

When deliberately upgrading the connector, inspect one scratch checkout, compare
the installed wheel source with it, update the pinned dependency closure and
provenance together, and run offline, audit, native build and harness checks.
Never infer private API compatibility from a passing dependency audit.
Restore/revert the manifest, adapter changes and provenance together if the upgrade
fails. Normal implementation rollback is a scoped Git revert and disposal of owned
test containers/images; no production service stop/delete is included.
