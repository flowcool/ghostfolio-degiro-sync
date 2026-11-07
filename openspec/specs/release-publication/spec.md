# release-publication Specification

## Purpose

Publish immutable DEGIRO candidates and stable images under the implemented IBKR channel rules, with exact candidate qualification in the existing connector laboratory before promotion.

## Requirements

### Requirement: Immutable candidate and stable channels

A published non-draft prerelease on main with exact tag `vX.Y.Z-rc.N`, N positive without leading zeros, SHALL publish only image tag `vX.Y.Z-rc.N`. Version components SHALL have no leading zeros. It SHALL NOT move stable, minor or latest tags. A stable published non-prerelease `vX.Y.Z` SHALL publish image tag `vX.Y.Z`; only the current stable release SHALL move latest. Preserve DEGIRO's `v` prefix in Compose, README and Renovate matching. This is an explicit naming difference from IBKR. Drafts, ordinary tag pushes, manual builds, branch builds, schedules and invalid tag/prerelease combinations SHALL not publish. Scheduled security checks SHALL remain read-only.

Publication SHALL serialize, reject an existing version and fail on ambiguous registry evidence. Recheck absence before manifest creation. Both native amd64/arm64 images SHALL pass security and isolated runtime checks; their verified configurations SHALL appear in the published manifest. Stable SHALL require the highest numbered RC for that version, use its exact source commit and copy its qualified image index without rebuilding. Stable SHALL NOT build a new image. The stable digest SHALL equal that RC digest; latest SHALL equal it only when this is the current stable release. A source refusal SHALL name both tags. Missing, stale or mismatched qualification SHALL refuse publication. Publication SHALL never deploy.

README SHALL explain the cutover, frozen existing aliases without deleting them, recording the installed digest, separate candidate qualification, highest-candidate promotion and why Renovate excludes prereleases, with its authoritative documentation link. Failed latest promotion SHALL permit explicit manual promotion of the verified digest only for the current stable release. Digest rollback SHALL preserve configuration and financial records. Security fixes SHALL use maintainer-selected releases and PATCH when compatibility-neutral.

#### Scenario: Offline channel and source guards

- **WHEN** `.venv/bin/python -m pytest -q tests/test_release_image.py tests/test_verify_release_image.py` runs valid stable/RC metadata, invalid prerelease combinations, leading zeros, occupied versions and highest-candidate source cases
- **THEN** only the specified channels qualify, output keeps `v`, invalid cases refuse publication, stable source mismatches name both tags, and native configuration checks remain enforced without registry access. A stable event without a matching qualified RC refuses publication.

#### Scenario: Candidate manifest and stable promotion

- **WHEN** the operator-authorized release operation runs `docker buildx imagetools inspect "$CANDIDATE_IMAGE"` for the exact published candidate
- **THEN** the manifest contains both checked architectures; retained before/after evidence proves latest and stable tags were unchanged, and a repeated publication refuses the occupied version.

#### Scenario: Candidate and stable source identity

- **WHEN** `git rev-parse "$RC_TAG^{commit}" "$STABLE_TAG^{commit}"` checks the tags selected by the release operation
- **THEN** the two commits are identical for promotion; a different commit is rejected before stable publication by the versioned preflight. The authorized release log proves that stable and RC index digests are equal and no native build ran for stable.

Baseline changed: the current release workflow checks source identity but rebuilds stable. Project guidance already requires promotion without rebuilding. This delta makes that requirement executable and preserves the v-prefixed image channels.

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

### Requirement: Automatic build identity

Each new release image SHALL embed target software version `X.Y.Z` and the full forty-character lowercase Git commit. A valid `vX.Y.Z-rc.N` or `vX.Y.Z` tag SHALL derive the same target software version. Runtime metadata and OCI version/revision labels SHALL agree on both architectures and in the checked and published images. Invalid metadata or a missing commit SHALL block publication.

Candidate registry tags SHALL retain their full RC suffix and DEGIRO's `v` prefix. Target software version SHALL NOT certify stable publication. No operator setting SHALL be needed to supply release identity.

Baseline changed: Dockerfile and release-image.yml currently embed the complete release tag as APP_VERSION and omit a runtime commit.

#### Scenario: Built image identity

- **WHEN** `.venv/bin/python scripts/smoke_container.py "$IMAGE"` runs against an isolated image built with synthetic valid release metadata
- **THEN** embedded version and full commit match its OCI labels, expected startup identity is present, malformed or contradictory metadata fails, and no financial request is sent.

### Requirement: Qualified candidate promotion

Stable promotion SHALL require one bounded `lab-qualification.json` asset on the highest published RC prerelease. The record SHALL bind schema, repository, source commit, RC tag, index digest, unique native amd64/arm64 manifest digests, successful empty/golden results, stopped lab cleanup and SHA256 proof hashes. It SHALL contain no credentials, private paths or work-tracker identifiers. Duplicate keys and ambiguous or incomplete records SHALL be rejected.

Before any registry write, promotion SHALL verify the candidate workflow signature, exact index/native digests, source ancestry, matching runtime/OCI identity on both architectures and unchanged release authority. Qualification is a maintainer attestation of the retained lab proof. Native CI alone SHALL NOT establish lab qualification. The publication workflow SHALL recheck version absence before writing and read back each written digest.

Missing signature or identity metadata in a legacy candidate SHALL block this path. Preserve the candidate and publish a new qualifying RC after approval; no overwrite or automatic legacy-recovery path is added. An uncertain registry write SHALL stop dependent writes and report possible partial publication. Never overwrite an occupied version.

Baseline: the dedicated DEGIRO lab requirement already owns both-lab proof; the qualification asset and candidate signature are new publication prerequisites.

#### Scenario: Read-only promotion plan

- **WHEN** `python scripts/promote_release_image.py --plan` runs with a synthetic release event and stubbed read-only registry/release responses
- **THEN** valid matching proof selects the highest RC; missing proof, duplicate keys, changed source, missing architectures or unsigned candidate refuse without a registry write.

#### Scenario: Exact index promotion

- **WHEN** `gh run view "$RELEASE_RUN" --log` inspects an operator-authorized stable promotion
- **THEN** it shows signature and qualification verification, no stable image build, exact RC/stable digest equality, correct latest selection, and refusal or an explicit partial-state stop after any uncertain write.
