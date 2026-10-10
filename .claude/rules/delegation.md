# Operating model — delegation, model right-sizing, infra handoff

DEGIRO operating policy. Sibling repositories retain their own configuration.

## Fleet

**Codex owns orchestration and implementation; CodeRabbit reviews PRs.**
Florent permanently disconnected Claude on 2026-10-09. Existing Claude-named
rule paths are compatibility locations, not a dependency on a Claude session.

## When to delegate

Work inline by default. Keep deterministic one-off work in the main thread and
use a script for repeated deterministic work. Spawn only when Florent explicitly
requests delegation or an applicable skill requires independent cross-review.
For authorized delegation, use the cheapest capable model available in the live
catalogue; return bounded findings with their sources. A retrieval task that needs
judgment returns the unresolved question rather than self-escalating.

## Infra handoff boundary — these never happen inside a sync repo

Produce the artifact here (image to build, secret pointer, origin to expose); hand execution
to the infra agent via the `handoff` skill → infra epic (`infra-8tt` family / current infra).

- **Deploy / Komodo / image**: build + push image, container deploy, supercronic cron in prod.
- **Secrets / SOPS**: rotation, writes to the off-git SOPS store, access pointers.
- **Network / DNS / Traefik**: exposure, reverse-proxy, allowlisted origins.

(Real Ghostfolio production writes stay a separate in-repo authorization gate, not an infra
handoff — the sync code owns that logic; only its authorization is gated.)

## Convergence discipline

A design must *decide*, not proliferate. When a feasibility / GO-NO-GO gate is open for a
project, **do not create a new `docs/design/*` doc** until the gate has a verdict. Close or
supersede an existing design doc before adding another. The gate is the forcing function;
more documents are not progress.
