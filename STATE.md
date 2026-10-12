# Project state

Last verified: 2026-10-12.

## Released source

- [v0.4.0](https://github.com/flowcool/ghostfolio-degiro-sync/releases/tag/v0.4.0)
  is the current stable release. Its tag targets
  [`5f47b83`](https://github.com/flowcool/ghostfolio-degiro-sync/commit/5f47b83dbffa4c6cc08836f1725328f469c9f94b).
- The release workflow passed its preflight, native `linux/amd64` and
  `linux/arm64` builds, and manifest publication. The published image is
  `ghcr.io/flowcool/ghostfolio-degiro-sync:v0.4.0`.
- Release images remain build artifacts, not a deployment or an authorization
  to perform financial writes.

## Working boundary

The connector is a DEGIRO-specific adapter around an immutable Ghostfolio core.
It defaults to safe simulation in the documented Compose setup. Account journals,
coverage evidence, uncertain results, identity checks and explicit `DRY_RUN`
remain required safeguards. Do not use this project to make a real broker,
vault, or financial-write call without separate operator authorization.

The supported operational scope is a 90-day Europe/Zurich rolling window, EUR
cash, EUR/USD/JPY quote currencies, and French-characterized cash statements.
It does not establish complete history or cost basis, and it never corrects or
deletes previously imported activities automatically.

## Continue work

Beads is the single source of truth for active work, ownership and blockers:

```sh
bd list --status=open --metadata-field project=ghostfolio-degiro-sync
bd list --status=in_progress --metadata-field project=ghostfolio-degiro-sync
```

The live-rollout authorization remains a separate Beads-owned decision. Read
the selected issue and its evidence before changing any runtime configuration.

## Canonical references

- [README](README.md): installation, configuration and operational limits.
- [Documentation index](docs/README.md): user and contributor paths.
- [Architecture](docs/architecture.md), [source contract](docs/source-contract.md)
  and [ADRs](docs/adr/README.md): implementation boundaries and decisions.
- [Contributing](CONTRIBUTING.md) and [build guarantees](.github/BUILD.md):
  offline validation, review and release process.

This file is an orientation aid. GitHub, Git and Beads are authoritative for
mutable release, source and work-tracking state.
