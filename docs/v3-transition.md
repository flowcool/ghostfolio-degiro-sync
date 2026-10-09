# Pinned external V3 transition boundary

The external CSV converter is a separate backfill tool, not the adapter's
accounting implementation or a completeness oracle. An actual synthetic run on
2026-10-09 (Europe/Zurich) used its unchanged
[V3 source at9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5](https://github.com/dickwolff/Export-To-Ghostfolio/blob/9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5/src/converters/degiroConverterV3.ts).
The public fixture [degiro_v3_transition.yaml](../tests/fixtures/degiro_v3_transition.yaml)
records all three input CSVs, captured output, producer/lock hashes, Node image
digest and timezone. It contains no private account or broker data.

| Synthetic input | Actual unchanged V3 output | Adapter consequence |
| --- | --- | --- |
| SELL2 TEST/USD for20, commission0.15EUR with same order ID | One SELL with fee0.15 in USD; no commission-currency conversion | API fixture with gross FX1.1 produces fee0.165USD. Existing CSV activity blocks import/cash; numeric proximity cannot adopt it |
| Same ISIN, two paid dividends10 and20USD at10:00 and14:00 on the same day, withholding1.5 and3USD | Only first dividend10/fee1.5 survives the day-based comment dedup | API payment identities preserve both; existing CSV row requires explicit reconciliation |
| Flatex interest and monetary-fund compensation | No activities | These source categories continue to block the entire adapter account; empty converter output is no proof that nothing happened |

The producer hard-codes `meta.version` to `v0`. It is not an immutable revision.
Observed behavior is bounded to this revision and these inputs, not every release
or broker locale. No source policy was changed or inferred from the converter.

## Reproduction boundary

From this repository, with Docker available and the already inspected checkout:

```sh
.venv/bin/python scripts/check_v3_transition.py --source /path/to/Export-To-Ghostfolio
```

This optional operator bench is separate from offline pytest and production.
It reads the pinned Git blob, verifies both source hashes, extracts only source
and package manifests into disposable scratch state, and never edits the external
checkout. Its dependency installation may contact the package registry while
building. Converter execution is network-disabled. The exact UUID-tagged image
and temporary files are removed afterward; shared image layers remain cached.

Use the already inspected scratch checkout at the exact recorded commit. Copy its
source, package manifest and lock into disposable scratch state, leaving that
checkout unchanged. Use the recorded Node22 image; the local Node20 does not meet
the producer's engine requirement. Install using `npm ci --ignore-scripts
--no-audit --no-fund` during image build. Dependencies are confined to the bench,
not this Python runtime or its offline test environment.

For execution, load each fixture `input_csv` into the native
`DeGiroConverterV3.processFileContents` callback boundary. Substitute only its
injected security lookup: reject every ISIN except the fixture's public
`US0378331005` and return symbol TEST. Set `GHOSTFOLIO_ACCOUNT_ID` to
`synthetic-csv-target`, omit tag IDs, and use `TZ=Europe/Zurich`. Serialize the
native activities unchanged. Exclude only the nondeterministic generation date
from captured metadata; retain its native version.

Run the built converter container non-root with `--network none`, `--read-only`,
a bounded tmpfs, no credentials, no production mounts, dropped capabilities and
no-new-privileges. No Yahoo call, broker authentication or Ghostfolio request is
needed to characterize the converter. Compare decoded output to each fixture's
`output`. The fixture's producer and package-lock hashes must match before rerun.

The [isolated native acceptance harness](isolated-acceptance.md) separately seeds
the actual captured SELL in its owned Ghostfolio instance, changing only the
synthetic account ID. It verifies exact native financial readback, then proves
that the API candidate's mismatched fee cannot bypass CSV-overlap blocking.
Offline regressions also cover distinct payments and full-ledger category gates.

## Limits and rollback

This establishes real synthetic conversion and conservative transition refusal.
It does not reconstruct the private July producer revision, restore its missing
original CSV, establish historical completeness, or implement reviewed adoption.
The [real read-only comparison](readonly-reconciliation.md) records four exact
destination matches and their financial association with fresh broker source
rows. Source seconds are truncated in the old output; neither these associations
nor the broader history capture prove complete safe adoption. No production
acceptance follows.

All bench state is disposable. Teardown the exact owned converter container and
Ghostfolio UUID project only; keep shared caches and other containers intact.
Roll back fixture/tests/harness/documentation with a scoped Git revert. The
external converter and immutable Ghostfolio core remain untouched.
