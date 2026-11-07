# Design

## Context

See proposal.md. Current release code rebuilds stable images. Current project guidance requires promotion of the qualified digest. The existing specification requires matching RC and stable source commits, but does not yet require equal digests.

## Goals / Non-Goals

Apply the portable startup and release mechanisms. Preserve the adapter and immutable core.

## Decisions

1. Reuse IBKR `scripts/release_image.py:release_identity`. Derive `X.Y.Z` from `vX.Y.Z[-rc.N]` and the full revision from the checked Git commit. Pass both values to checked and published builds. Reject a versioning package: Git and existing build actions already supply the inputs.
2. Adapt IBKR `entrypoint.sh` and `app.main`. Print a static DEGIRO banner before the dynamic identity. Print identity for each normal application cycle. Keep the isolated notification worker silent. Keep explicit command execution and exit codes.
3. Adapt IBKR `scripts/promote_release_image.py` and its release workflow. Require the highest RC, a bounded `lab-qualification.json` asset, two stopped lab results, exact source/native digests and a verified workflow signature. Add the pinned build-time Cosign action. Preserve DEGIRO's image-tag prefix. Stable copies the index and reads back digest equality. A direct stable build is no longer allowed.
4. Keep core pin `403b4cc`. Against inspected IBKR main `f9a2b113`, ten selected functions are unchanged. `accepted_import_subset` adds `effective_currency`; its closure includes `CurrencyEvidence`, `DESTINATION_CURRENCIES`, `Mapping`, `Any` and `TypedDict`. Adoption needs separate nullable-currency scenarios, including invalid current-profile precedence over legacy context. `ghost_update_cash_balance` adds outcome diagnostics. DEGIRO already fences cash in its journal. Neither difference belongs in this presentation/publication change.
5. Retain existing bounded reports and notifications. Gitleaks, Scorecard and wheel hash locking remain separate security candidates, with their own evidence and maintenance cost.

## Risks / Trade-offs

- A target version can appear in an RC → retain the full candidate registry tag; document that the log does not certify stable publication.
- Older RCs lack signatures or qualification assets → refuse promotion. Build a new RC from the approved source. Keep old images and proof.
- Workflow code follows the tagged commit → require the new release source to contain the promotion mechanism.

## Migration Plan

Deliver one implementation and one qualified release. Preserve existing aliases. Roll back source with one scoped Git revert. Keep journals, evidence and financial records. Stable publication and deployment retain separate GO.
