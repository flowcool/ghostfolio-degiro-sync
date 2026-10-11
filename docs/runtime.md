# Container runtime

The supported deployment is Docker Compose; see the root [README](../README.md) for all user steps and variables. Pull the published version or a reviewed image digest. No host interpreter, host secret loader or custom infrastructure platform is required.

## Isolation

The image runs as UID/GID 10001. Compose uses a read-only root filesystem, dropped capabilities, no-new-privileges and a 32 MiB private tmpfs. Only the journal directory is writable persistently; the verified mapping is mounted read-only. Create both mounts before launching. Docker administrators can inspect environment credentials and backups, so restrict access to the daemon and host.

Each broker execution creates a mode 0700 temporary Bitwarden CLI state directory on tmpfs. The CLI receives only vault credentials and its private state location; broker/Ghostfolio credentials and inherited vault sessions are excluded. It authenticates, unlocks, syncs, retrieves the exact item and logs out. Calls are noninteractive with a 30-second per-command limit and a 120-second overall budget. Errors and stderr remain private. Temporary state is removed on success or failure; the container tmpfs disappears when the container is removed. A forcibly interrupted process can leave encrypted temporary files until removal, without making them a reusable credential source.

## Dependencies and scheduler

Runtime Python dependencies are pinned in requirements.txt. Supercronic and the OSS Bitwarden CLI have separate version and SHA256 pins for amd64/arm64 in Dockerfile. Bitwarden's license/source notice ships in `/usr/local/share/bitwarden`. See [upstreams](upstreams.md) for monitoring and propagation.

Empty CRON runs once. Five numeric fields start Supercronic without an immediate run. TZ is Europe/Zurich in Compose and the image includes tzdata. Sentry settings are removed from the managed scheduler environment so inherited settings cannot activate its HTTP delivery paths. Real native-architecture smoke tests verify run-once, cron execution and timezone data with synthetic inputs.

## Updates and rollback

Stop the importer, preserve mapping/journals, pull/select the reviewed image and recreate the service. Restart alone retains its environment. API-key/master-password changes require recreation; DEGIRO item changes are fetched on the next execution. Source rollback uses a scoped Git revert; it does not reverse account activities or cash. An older version may reject a newer journal: use a reviewed forward fix or explicit migration instead of deleting state.

Developer-only lab and synthetic credential-delivery checks are documented in CONTRIBUTING.md. They never use a real vault or broker account.

Official US cloud origins are normalized to the CLI's `https://bitwarden.com`
configuration, which selects its separate API/identity defaults. EU cloud origins
select explicit `https://api.bitwarden.eu` and `https://identity.bitwarden.eu`
endpoints; a web-vault hostname alone is not a self-hosted API origin. Other HTTPS
origins retain the CLI's self-hosted server behavior. This is an adapter mapping,
not a transport redirect or an operator TLS override.
