# Spec Delta

## Purpose

Publish immutable DEGIRO candidates and stable images under the implemented IBKR channel rules, with exact candidate qualification in the existing connector laboratory before promotion.

## ADDED Requirements

### Requirement: Immutable candidate and stable channels

A published non-draft prerelease on main with exact tag `vX.Y.Z-rc.N`, N positive without leading zeros, SHALL publish only image tag `vX.Y.Z-rc.N`. Version components SHALL have no leading zeros. It SHALL NOT move stable, minor or latest tags. A stable published non-prerelease `vX.Y.Z` SHALL publish image tag `vX.Y.Z`; only the current stable release SHALL move latest. Preserve DEGIRO's `v` prefix in Compose, README and Renovate matching. This is an explicit naming difference from IBKR. Drafts, ordinary tag pushes, manual builds, branch builds, schedules and invalid tag/prerelease combinations SHALL not publish. Scheduled security checks SHALL remain read-only.

Publication SHALL serialize, reject an existing version and fail on ambiguous registry evidence. Recheck absence before manifest creation. Both native amd64/arm64 images SHALL pass security and isolated runtime checks; their verified configurations SHALL appear in the published manifest. When candidates exist for that version, stable SHALL point to the same commit as the highest candidate number; a refusal SHALL name both tags. Publication SHALL never deploy.

README SHALL explain the cutover, frozen existing aliases without deleting them, recording the installed digest, separate candidate qualification, highest-candidate promotion and why Renovate excludes prereleases, with its authoritative documentation link. Failed latest promotion SHALL permit explicit manual promotion of the verified digest only for the current stable release. Digest rollback SHALL preserve configuration and financial records. Security fixes SHALL use maintainer-selected releases and PATCH when compatibility-neutral.

#### Scenario: Offline channel and source guards

- **WHEN** `.venv/bin/python -m pytest -q tests/test_release_image.py tests/test_verify_release_image.py` runs valid stable/RC metadata, invalid prerelease combinations, leading zeros, occupied versions and highest-candidate source cases
- **THEN** only the specified channels qualify, output keeps `v`, invalid cases refuse publication, stable source mismatches name both tags, and native configuration checks remain enforced without registry access.

#### Scenario: Candidate manifest and stable promotion

- **WHEN** the operator-authorized release operation runs `docker buildx imagetools inspect "$CANDIDATE_IMAGE"` for the exact published candidate
- **THEN** the manifest contains both checked architectures; retained before/after evidence proves latest and stable tags were unchanged, and a repeated publication refuses the occupied version.

#### Scenario: Candidate and stable source identity

- **WHEN** `git rev-parse "$RC_TAG^{commit}" "$STABLE_TAG^{commit}"` checks the tags selected by the release operation
- **THEN** the two commits are identical for promotion; a different commit is rejected before stable publication by the versioned preflight.

Baseline: `.github/workflows/release-image.yml`, `scripts/release_image.py`, `scripts/verify_release_image.py`, `compose.yaml` and `renovate.json`. DEGIRO already accepts semantic-version prereleases and publishes the original tag including `v`. This change narrows candidate grammar and adds explicit stable/RC source promotion checks. Offline implementation completes before archive; real publication and manifest proof follow archive/main replay under an approved unused tag. Offline checks do not claim registry proof.

### Requirement: Dedicated DEGIRO acceptance in the existing lab

Before production use or stable promotion, the exact published candidate digest SHALL pass the versioned infra runner against both the empty first-install lab and the golden-copy upgrade lab. Add a dedicated DEGIRO connector container with private state, mapping and isolated fixture credentials. Bind the digest in connector-specific instance configuration after publication; do not reuse `LAB_IBKR_IMAGE` or IBKR state. Obtain exclusive use before a versioned empty/golden reset. Never reset a shared instance owned by another session. No production credentials are allowed.

For repeatable financial acceptance, bind fixed synthetic/anonymized DEGIRO broker responses, source window, injected clock, mapping and expected payloads to each scenario. Adapt the existing versioned `scripts/community_journey.py` transport-fixture pattern outside the shipped image: replay broker/vault responses only, while destination requests exercise the actual installed candidate against the lab. The standard image SHALL gain no production snapshot-override setting. Record input hashes; live rolling broker reads are not deterministic fixture proof. Real broker access remains a separate authorized preview. When golden history has no eligible DEGIRO rows, qualify migration on explicitly seeded isolated DEGIRO rows and preserve the original golden rows; do not claim synthetic coverage as real-history proof.

Acceptance SHALL prove complete payloads, exact created/readback fields, unchanged protected history and other accounts, fee/interest UUID associations, both identity generations, zero repeat creations, cash/uncertainty fences and report/native evidence. It SHALL also prove all-history migration preview, exact conversion, interrupted/uncertain stop, comment reversal, preserved new v1 imports and safe halt in simulation using the same candidate. No reader-only release is required. Golden restore SHALL preserve legacy/null fields without treating them as candidate proof. Ignore only proven derived valuation fields when checking stored-state preservation. Incomplete evidence SHALL block promotion. A failed digest SHALL be replaced and both scenarios replayed. Stop owned instances and retain containers/logs.

#### Scenario: First-install and upgrade evidence

- **WHEN** the approved operation runs `python3 lab.py compare --instance ghostfolio-lab --run-dir "$RUN1" --expected "$EXPECTED"`, then `python3 lab.py idempotence --instance ghostfolio-lab --run-dir "$RUN2" --expected "$EXPECTED" --before "$RUN1/after.json"`, then `python3 lab.py report --instance ghostfolio-lab --run-dir "$RUN3" --expected "$EXPECTED" --before "$RUN2/after.json" --checker "$DEGIRO_CHECKER"`, and the corresponding golden-instance checks with its own paths and `--baseline-run "$GOLDEN_BASELINE"`
- **THEN** both exact-digest scenario replays produce recorded PASS results, complete financial readback and zero repeated imports; the versioned DEGIRO checker verifies report/native evidence without IBKR-only assumptions.

The runner and `financial_checks.py` SHALL use an explicit DEGIRO contract, retaining the IBKR contract for IBKR runs. Remove DEGIRO dependence on IBKR-only ENV, `connector=ibkr`, the 365-day Flex check, Yahoo lookup for MANUAL profiles, positive-only fee/interest prices, raw submitted-symbol equality after UUID rewrite, IBKR trade/dividend summary strings, dividend-only positive coverage and a fixed checker filename. Preserve strict numeric/ownership checks with DEGIRO's type-specific valid zero cases. Bind the versioned `scripts/check_degiro_report.py` checker and full report coverage, including runs with no dividend. A fixed, validated private-HTTP warning may be admitted only by the scoped lab contract; unexpected warnings still fail. No global warning bypass is permitted.

The approved operation SHALL bind every variable to owned inputs and validate launch, environment, source replay, digest pin, checker and financial evidence before dispatch. Adding a container alone does not qualify DEGIRO.

The owning operation SHALL provide the exact executable acceptance commands and targets before any live action. Proposal approval does not authorize a broker login, snapshot acquisition, financial write or deployment. No mandatory soak duration or count of daily cycles applies.
