# Rootless run-once and cron runtime

The image follows the IBKR Python 3.12 + supercronic harness. Its Python base is
pinned by multi-platform digest in `Dockerfile`; supercronic v0.2.49 has separate
official binary SHA256 pins for amd64/arm64. Only `requirements.txt` is installed,
with the complete direct/transitive dependency closure. Dev pytest/pip-audit,
optional connector QR/quotecast packages, Git state and private snapshots do not
ship. `.dockerignore` allowlists the build inputs and COPY lists runtime files.

Managed cron enables neither a Go HTTP listener nor supercronic Sentry reporting:
the entrypoint clears inherited `SENTRY_DSN`, `SENTRY_ENVIRONMENT` and
`SENTRY_RELEASE` before validation and execution. Broker HTTP stays in Python.
The expiring exact-CVE exceptions in `.trivyignore` rely on that boundary and the
pinned upstream binary. Reassess before command/entrypoint overrides or enabling
Go network features; exceptions do not establish safety for those configurations.

The app runs as UID/GID10001. Its files remain owned by root, and the crontab is
created in the container's writable temporary directory. Read-only root filesystem
operation with a `/tmp` tmpfs is supported. `DRY_RUN=1` is the image default;
changing that environment value does not establish history proof or production
authorization. No image publication, deployment or production smoke is performed
by the validation workflow.

## Build and isolated validation

CI configures Google's public Docker Hub cache in the Docker daemon on each
disposable runner, preserving existing daemon settings and other mirrors. This
avoids the shared runners' anonymous Docker Hub quota on cache hits. The Python
OCI index digest remains literal in the unchanged `Dockerfile`, with no
floating-tag fallback. A cache miss falls back to Docker Hub at the same digest
and can still encounter its quota. Google does not guarantee cache retention.
See the
[Google cache documentation](https://cloud.google.com/artifact-registry/docs/pull-cached-dockerhub-images).
Both amd64 and arm64 images at this exact digest were pulled successfully from
the cache before introducing the CI override; native CI verifies build and smoke
behavior on both architectures. No registry credentials are introduced. Local
Docker daemon configuration and production hosts are unchanged.

To roll back, revert the scoped change commit (or `git revert -m 1
<merge-commit>` after integration) to remove the CI daemon-configuration step and
documentation together. The next disposable runner uses its original registry
configuration. This affects builds only and requires no production service action.

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

## Prepared unattended credential contract

The completed Bitwarden bootstrap and the existing agentvm SOPS loader are the
starting point, not installed production provisioning. `secrets.pointer.yaml`
identifies the encrypted broker store and host loader. Bitwarden is used only
for authorized bootstrap/renewal; the runtime does not log into the vault.
The prepared boundary reuses that loader and Docker's environment-name passing,
without adding SOPS, an age key, a decryptor or a secret service to the app image.

| Boundary | Contract |
| --- | --- |
| Broker source | Off-git SOPS dotenv, exactly `DEGIRO_USERNAME`, `DEGIRO_PASSWORD`, `DEGIRO_TOTP_SECRET`; restricted host-side access |
| Host decrypt | Existing `run-degiro-env.py` runs SOPS with captured output, a 60-second limit and the host key; validates the complete nonempty key set before executing a child |
| Ghostfolio source | Independently provisioned `GHOST_TOKEN` in the launcher environment; an already valid bearer, with no token exchange in this scope |
| Injection | `docker run --env NAME` copies values from the loader's child environment; values never appear in argv or a plaintext env file |
| Container access | UID/GID10001 receives the four variables; it cannot access the SOPS source, host key or Bitwarden |
| Cron | Supercronic's Python child inherits the container environment; no decrypt or vault access happens per minute/job |
| Restart/refresh | Start a fresh host loader process and recreate the container. The environment is a snapshot; direct `docker restart` retains old values and is outside this contract |
| Unavailable source | Missing/unreadable store, unavailable key/decryption failure, timeout or invalid key set stops the loader before Docker/application execution; stale inherited broker variables do not provide a fallback |

Infra owns target-host provisioning and refresh, including the independent
Ghostfolio bearer lifecycle. The supported launcher uses `--restart=no` and
foreground `docker run --rm`: any host supervisor restart must rerun the loader
and create a new container. A credential rotation requires a controlled stop
and recreation of a cron container; changing the encrypted file cannot update
an existing process. Source loss while an already running cron exists does not
revoke its in-memory credentials; infra must stop it if continued use is no
longer authorized. Job/authentication errors remain application failures, with
no automatic vault refresh or broker-login retry.

The existing loader inherits `GHOST_TOKEN` from its caller. Its private dotenv
format uses one literal nonempty value per line, split on the first `=`; it
does not evaluate shell quoting or expansion and does not support embedded
newlines. Infra must preserve that representation when provisioning/rotating.
Host administrators and Docker-daemon operators can read process/container
environments. Docker also persists the injected values in container metadata
for the container's lifetime; daemon backups/snapshots may retain them after
removal. SOPS protects the source store, not that Docker metadata. Target-host
Docker-data and backup protection therefore need explicit infra verification.
Restrict that access; never dump Docker inspection, decrypted
output, a shell trace or a crash/core dump. This boundary is not a mechanism
for hiding credentials from the Docker administrator.

### Synthetic preparation evidence

After building the image above, run:

```sh
.venv/bin/python scripts/check_credential_delivery.py \
  --loader /home/flow/claude_project/infra/rotation/run-degiro-env.py \
  --image ghostfolio-degiro-sync:local
```

The driver accepts only the reviewed loader bytes, SHA256
`f605a539aa0348cc82d161861d5630d381c23db52a513cb4bbc65bcebd8ecc51`.
It substitutes a synthetic store, SOPS subprocess and child execution boundary
before calling the loader; no real encrypted store, key, vault or SOPS container
is used. Six unavailable/invalid-source cases must suppress private diagnostics
and execute no child. Valid output supplies all three broker variables and
preserves the independently supplied synthetic bearer.

The resulting synthetic environment enters disposable, network-disabled,
rootless containers through environment names. The actual entrypoint and actual
minute cron run a hashes-only replacement of the broker script, proving child
delivery without broker/HTTP activity. Two generations exercise recreation and
credential refresh for both run-once and cron. Passing this is harness evidence,
not actual broker authentication or proof that the target host is provisioned.

Ownership records under ignored `tmp/credential-recovery/` contain only names,
IDs and the UUID label, mode0600. Normal cleanup rechecks exact ID/name/label,
then removes only those containers. Failed cleanup retains the record; inspect
only identity and label before retrying exact-ID removal. SIGKILL can require
that manual recovery. Never prune the host or inspect `Config.Env`.

### Installation and rollback handoff to infra

The target needs Docker, the approved immutable app image, UID/GID10001 access
to its mounted files, a host-side private SOPS store encrypted for that host's
key, a bounded host loader equivalent to the reviewed agentvm loader, and
independent bearer provisioning. The current agentvm key/path is not proof of
target-host decryption access. Infra selects the target host, supervisor,
source/key paths and refresh procedure during the separately authorized rollout.

The launcher template is an argument vector, not a shell secret-substitution
recipe: invoke `python3 HOST_LOADER docker run --rm --restart=no`, followed by
`--env DEGIRO_USERNAME --env DEGIRO_PASSWORD --env DEGIRO_TOTP_SECRET
--env GHOST_TOKEN`, explicitly allowlisted nonsecret account/origin settings,
`DRY_RUN=1`, and the reviewed image digest. Supply `CRON` only for cron mode.
Use a read-only mapping mount and, for live mode, a persistent private0700
`STATE_DIR` owned by UID10001. The production network must reach the approved
broker/Ghostfolio origins; the validation driver's `--network=none` is lab-only.
No published app port is needed. Preserve existing hardening (read-only root,
tmpfs, dropped capabilities and no-new-privileges). Do not use a Compose
plaintext env file or place secret values in Compose interpolation.

Before installation, infra must verify target decryption/UID access, install
the supervisor/refresh procedure and its controlled stop mechanism, and record
the exact old/new image digests and restoration commands. Production approval,
account backup/restore and scheduled financial reconciliation belong to the
rollout gate; this preparation does not authorize them. Rollback here is the
exact preparation Git revert and cleanup of positively owned synthetic
containers. No existing SOPS store/loader, app image, broker session or
production service is modified. Production rollback must stop the owned
scheduler, restore the approved prior image/config and rerun the host loader;
it must not resurrect stale plaintext credentials or claim to undo activities.

Without `CRON`, the entrypoint runs `--sync` once. With `CRON`, exactly five
numeric schedule fields are accepted and supercronic validates them. Named
shortcuts and embedded commands/newlines are rejected. Only the fixed sync command
is written to the crontab; no environment-provided command is evaluated.
Supercronic retains its default non-overlapping scheduling for this single job.
Independent instances targeting the same account still require operator control.
Live invocations also require one shared private persistent `STATE_DIR` for their
account lock and durable intent. See [recovery.md](recovery.md); do not use the
container tmpfs for that state. No production mount is created by this scaffold.

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
