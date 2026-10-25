## MODIFIED Requirements

### Requirement: Guarded historical identity conversion

The versioned maintenance command SHALL convert eligible historical identities in the same delivery as the new writer. It SHALL be separate from scheduled sync and from DRY_RUN=false. Preview approval does not authorize real writes. An operation plan validated once SHALL bind exact executable commands, manifest hash, owner/account scope, destination image/version, backup, writer exclusion, unsettled-request checks, expected write count, measured pacing, stop rules and recovery. Prepare this operation during the delivery; do not require a separate reader-only release or waiting period.

Maintenance SHALL accept semantic Ghostfolio versions at or above 3.86.0 without an exact-version or hard-coded upstream source commit requirement. A prerelease of the minimum version is below the floor; build metadata does not change precedence. Invalid or older versions SHALL fail before authentication or writes. Each operation SHALL still bind its observed destination version and image to the reviewed snapshot and approval. Newer-version eligibility SHALL preserve the existing authorization, per-class qualification, ownership, financial preservation, pending-request, settlement and reversal requirements.

Before the first write, stop competing writers, verify a recoverable backup and re-read complete unredacted destination state. Reject stale fingerprints, changed mappings/image, occupied identities or scope drift. Use existing private authentication and bounded transport with a dedicated maintenance allowlist for `PUT /api/v1/activities/{id}`. The normal sync transport SHALL NOT gain permission to modify historical activities.

Qualify the exact target UpdateOrderDto and update effects from its pinned implementation and the lab before enabling conversion. An API request may require financial fields even though only the comment may change. Construct an explicit allowlist; never echo a GET object. Preserve exact numeric transport, activity currency, tags, account and profile identity. Prove MANUAL fee/interest/compensation, valid zero values and returned UUID profiles, not just Yahoo BUY/SELL/DIVIDEND. If any activity class cannot be preserved, mark it unqualified and leave its rows intact. Background/profile effects or unproven pacing block that class; no financial correction, insert, delete, cash or platform write is permitted.

Persist each original row fingerprint, comment and bounded request as pending in a locked private YAML journal before dispatch. Prove exact post-write readback and unchanged protected rows before advancing. Stop on failed/uncertain HTTP, normalization, partial completion or changed context. Retain pending state and confirmed subsets; never retry automatically. An unchanged/old readback alone does not prove that a delayed request cannot complete. Independent completion/cancellation evidence is required before retry or reversal; otherwise keep the operation stopped.

The API MAY omit `isDraft`; maintenance SHALL still enforce draft and exclusion tags. An owned comment PUT MAY advance only its row's backend-managed Order `updatedAt` monotonically. Maintenance SHALL retain the complete observed postimage, including that timestamp, for conversion and reversal. It SHALL NOT send timestamps in the update DTO or relax checks on other fields or protected rows.

#### Scenario: Conversion and uncertain completion

- **WHEN** `.venv/bin/python -m pytest -q tests/test_identity_migration.py -k apply` exercises exact qualified DTOs, MANUAL/zero values, stale manifests, concurrent writers, decimal loss, profile effects, partial success, delayed writes and timeouts
- **THEN** only approved comments change, every other stored field is preserved, journal intent precedes each request, exact readback verifies confirmed rows, and every uncertain result stops without retry.

#### Scenario: Newer Ghostfolio maintenance

- **WHEN** conversion and reversal use a newer semantic destination version with complete matching operation evidence
- **THEN** version eligibility permits both operations without an old source commit, while invalid or older versions and changed approved destinations fail before authentication or writes.
