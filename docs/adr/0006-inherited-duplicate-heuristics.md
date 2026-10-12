---
status: accepted
date: 2026-10-12
---

# Retain inherited manual matching with explicit omission risk

Rolling mode retains IBKR-style proximity matching for destination activities
without canonical DEGIRO comments. A dividend in the same account and symbol
within three UTC calendar days, inclusive, counts as already represented; the
rule does not compare amount, price, fee or currency and does not consume the
existing dividend. One manual dividend can therefore suppress multiple genuine
payments without an error. A BUY/SELL of the same account, symbol and side within
two UTC calendar days, inclusive, matches when quantity differs by less than
0.001; the nearest qualifying row is consumed once. Nearby trades with no matching
quantity are refused. These rules do not prove exact historical accounting.

Accept the omission risk to avoid duplicate rolling imports alongside manually
maintained history. Canonical DEGIRO identities instead require exact unchanged
financial evidence and never fall back to proximity. Whole-account evidence and
holdings checks remain mandatory, but dividends do not alter holdings and those
checks cannot establish that no payment was omitted.

DRY_RUN and optional plan output already report `already_imported`, `manual_match`
and `duplicate_candidate` counts. `manual_match` aggregates heuristic exclusions;
it does not identify which payments were suppressed. Consider an opt-in private
per-candidate reason report in a separately reviewed change, with no credential
or public financial logging. Strict-only manual matching would need a migration
policy for existing history; broader automatic matching would increase silent
omission risk. Neither is introduced by this decision.
