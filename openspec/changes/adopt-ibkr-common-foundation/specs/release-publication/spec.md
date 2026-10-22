# Spec Delta

## Purpose

Publish immutable DEGIRO candidates and stable images under the implemented IBKR channel rules, with exact candidate qualification in the existing connector laboratory before promotion.

## ADDED Requirements

### Requirement: Immutable candidate and stable channels

A published non-draft prerelease on main with exact tag `vX.Y.Z-rc.N`, N positive without leading zeros, SHALL publish only `X.Y.Z-rc.N`. Version components SHALL have no leading zeros. It SHALL NOT move stable, minor or latest tags. A stable published non-prerelease `vX.Y.Z` SHALL publish `X.Y.Z`; only the current stable release SHALL move latest. Drafts, ordinary tag pushes, manual builds, branch builds, schedules and invalid tag/prerelease combinations SHALL not publish. Scheduled security checks SHALL remain read-only.

Publication SHALL serialize, reject an existing version and fail on ambiguous registry evidence. Recheck absence before manifest creation. Both native amd64/arm64 images SHALL pass security and isolated runtime checks; their verified configurations SHALL appear in the published manifest. When candidates exist for that version, stable SHALL point to the same commit as the highest candidate number. Publication SHALL never deploy.

README SHALL explain the cutover, frozen existing aliases without deleting them, recording the installed digest, separate candidate qualification, highest-candidate promotion and why Renovate excludes prereleases, with its authoritative documentation link. Failed latest promotion SHALL permit explicit manual promotion of the verified digest only for the current stable release. Digest rollback SHALL preserve configuration and financial records. Security fixes SHALL use maintainer-selected releases and PATCH when compatibility-neutral.

#### Scenario: Candidate manifest and stable promotion

- **WHEN** the operator-authorized release operation runs `docker buildx imagetools inspect "$CANDIDATE_IMAGE"` for the exact published candidate
- **THEN** the manifest contains both checked architectures; retained before/after evidence proves latest and stable tags were unchanged, and a repeated publication refuses the occupied version.

#### Scenario: Candidate and stable source identity

- **WHEN** `git rev-parse "$RC_TAG^{commit}" "$STABLE_TAG^{commit}"` checks the tags selected by the release operation
- **THEN** the two commits are identical for promotion; a different commit is rejected before stable publication by the versioned preflight.

Baseline: `.github/workflows/release-image.yml`, `scripts/release_image.py` and `scripts/verify_release_image.py`. Candidate support is new. Acceptance requires an approved unused candidate tag; offline checks do not claim registry proof.

### Requirement: Dedicated DEGIRO acceptance in the existing lab

Before production use or stable promotion, the exact published candidate digest SHALL pass the versioned infra runner against both the empty first-install lab and the golden-copy upgrade lab. Add a dedicated DEGIRO connector container to the existing lab infrastructure, with its own private state, mapping and broker credentials. Do not share IBKR journals or disrupt another session's container.

Acceptance SHALL prove complete expected payloads, exact created/readback fields, unchanged protected history and other accounts, fee/interest UUID associations, dual-generation deduplication, zero new rows on repeat, cash and uncertainty fences, and readable report/native evidence. Golden restore SHALL preserve legacy/null fields without treating them as candidate proof. Current valuation changes SHALL not be mistaken for stored financial mutations. Incomplete evidence SHALL block promotion. A failed digest SHALL be replaced and both scenarios replayed for the replacement. Stop only owned instances after use; retain containers and logs.

#### Scenario: First-install and upgrade evidence

- **WHEN** the approved operation runs `python3 lab.py compare --instance ghostfolio-lab --run-dir "$RUN1" --expected "$EXPECTED"`, then `python3 lab.py idempotence --instance ghostfolio-lab --run-dir "$RUN2" --expected "$EXPECTED" --before "$RUN1/after.json"`, then `python3 lab.py report --instance ghostfolio-lab --run-dir "$RUN3" --expected "$EXPECTED" --before "$RUN2/after.json" --checker "$DEGIRO_CHECKER"`, and the corresponding golden-instance checks with its own paths and `--baseline-run "$GOLDEN_BASELINE"`
- **THEN** both exact-digest scenario replays produce recorded PASS results, complete financial readback and zero repeated imports; the versioned DEGIRO checker verifies report/native evidence without IBKR-only assumptions.

The existing runner's IBKR defaults SHALL be replaced by explicit connector selection for DEGIRO runs. The operation SHALL bind every variable to owned inputs and validate the DEGIRO launch, environment and evidence contract before dispatch. Adding a container alone does not qualify DEGIRO.

The owning operation SHALL provide the exact executable acceptance commands and targets before any live action. Proposal approval does not authorize a broker login, snapshot acquisition, financial write or deployment. No mandatory soak duration or count of daily cycles applies.
