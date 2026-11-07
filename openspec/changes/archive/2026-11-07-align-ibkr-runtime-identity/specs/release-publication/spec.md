# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
