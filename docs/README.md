# Documentation

## Users

The root [README](../README.md) is the single setup and configuration reference.

- [Read-only discovery](read-only.md): private account captures.
- [Synchronization](synchronization.md): financial contracts and supported modes.
- [Authentication](ghostfolio-auth.md): credentials, origin and transport policy.
- [Notifications](notifications.md): failure-alert scope and limitations.
- [Recovery](recovery.md): uncertain imports and explicit local confirmation.

## Contributors

- [Project state](../STATE.md): compact maintainer entry point; Git and Beads remain authoritative for mutable state.
- [Contributing](../CONTRIBUTING.md): offline tests, builds and synthetic labs.
- [Architecture](architecture.md), [glossary](../GLOSSARY.md) and [decisions](adr/README.md).
- [Core provenance](../CORE_PROVENANCE.md): immutable projection and propagation.
- [Upstreams](upstreams.md), [runtime](runtime.md) and [Compose definitions](compose.md).
- [Source contract](source-contract.md), [fees](fee-contract.md),
  [cash yield](interest-compensation-policy.md) and [mode evidence](prospective-sync.md).
- [Isolated acceptance](isolated-acceptance.md) and [CSV transition](v3-transition.md).
- [Build and release guarantees](../.github/BUILD.md).
- [Supply chain](supply-chain.md): binary transport and Python hash-lock evaluation.

Agent guidance lives under `.claude/`; it is not deployment documentation.
The [archived GitHub bootstrap snapshot](archive/github-setup.md) is historical.
