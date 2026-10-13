# Pinned external V3 transition boundary

The external CSV converter is a separate backfill tool, not the adapter's
accounting implementation or a completeness oracle. An actual synthetic run on
2026-10-09 (Europe/Zurich) used its unchanged
[V3 source at 9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5](https://github.com/dickwolff/Export-To-Ghostfolio/blob/9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5/src/converters/degiroConverterV3.ts).
The public fixture [degiro_v3_transition.yaml](../tests/fixtures/degiro_v3_transition.yaml)
records all three input CSVs, captured output, producer/lock hashes, Node image
digest and timezone. It contains no private account or broker data.

| Synthetic input | Actual unchanged V3 output | Adapter consequence |
| --- | --- | --- |
| SELL 2 TEST/USD for 20, commission 0.15 EUR with same order ID | One SELL with fee 0.15 in USD; no commission-currency conversion | API fixture with gross FX 1.1 produces fee 0.165 USD. Existing CSV activity blocks import/cash; numeric proximity cannot adopt it |
| Same ISIN, two paid dividends 10 and 20 USD at 10:00 and 14:00 on the same day, withholding 1.5 and 3 USD | Only first dividend 10/fee 1.5 survives the day-based comment dedup | API payment identities preserve both; existing CSV row requires explicit reconciliation |
| Flatex interest and monetary-fund compensation | No activities | These source categories continue to block the entire adapter account; empty converter output is no proof that nothing happened |

The producer hard-codes `meta.version` to `v0`. It is not an immutable revision.
Observed behavior is bounded to this revision and these inputs, not every release
or broker locale. No source policy was changed or inferred from the converter.

## Reproduction boundary

The fixture was produced by an optional Docker bench, `scripts/check_v3_transition.py`,
removed with the contributor lab on 2026-10-13
([source and full procedure at removal](https://github.com/flowcool/ghostfolio-degiro-sync/blob/15d595f/docs/v3-transition.md#reproduction-boundary)).
Offline regressions in `tests/test_degiro_v3_transition.py` still compare the
pinned output with the adapter; they need no Docker or network.

## Limits and rollback

This establishes real synthetic conversion and conservative transition refusal.
It does not reconstruct the private July producer revision, restore its missing
original CSV, establish historical completeness, or implement reviewed adoption.
Private account comparisons do not establish complete safe adoption and are
not community compatibility evidence. Source seconds may be truncated in old
converter output; matching a subset of destination rows does not certify history.
No production acceptance follows.

Roll back fixture, tests and documentation with a scoped Git revert. The
external converter and immutable Ghostfolio core remain untouched.
