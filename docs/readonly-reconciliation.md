# Observed private-source reconciliation boundary

Read-only characterization on 2026-10-09 (Europe/Zurich) followed the authoritative
infra CMDB and Ghostfolio Compose to the owning UGreen host. Runtime package
version was 3.81.0. An existing environment-only bearer in the owning IBKR runtime
performed exactly GET `/api/v1/account` and GET `/api/v1/activities` on the approved
private origin. No token exchange, financial mutation, deployment, scheduler run
or production test occurred. Raw data was captured locally in ignored private
files with mode 0600; bearer credentials stayed in the remote process environment.

The complete response contained 1,017 activities across six accounts. The DEGIRO
target had 145 rows, an unredacted balance and EUR currency. The adapter accepted
the complete financial/ownership context, retaining unrelated provider rows.
This proves compatibility with that saved response, not current write readiness.

The canonical external converter's output directory contained a V3 JSON produced
on 2026-07-16, with four dividends. Every row matched exactly one existing target
activity on all ten canonical DTO fields: account, comment, currency, data source,
UTC instant, fee, quantity, symbol, type and price. The four matched created IDs
were distinct. No proximity, rounding or inferred currency was used. This is an
actual output comparison, not a new converter run or permission to adopt entries.
The output metadata records version `v0` and a generation date on 2026-07-16;
it does not identify an immutable converter revision. The original input directory
was empty, so the source CSV, exact producer revision and complete historical
coverage could not be independently reconstructed from that old output. A new
direct broker export is now available privately; the old missing input does not
prevent a fresh source-pinned transition proof.

The subsequent extended direct broker capture uniquely traces all four old V3
comments to source dividends by product ISIN and local minute. Every payment has
one exact product/currency/date/value-date withholding partner; gross amount,
withholding fee, currency and quantity 1 agree exactly with the saved V3 output.
The four V3 timestamps truncate the source seconds (differences 18, 55, 1 and 41
seconds), rather than shifting the timezone. This is explicit source association,
not permission for proximity-based adoption or proof of canonical API identity.
It does not establish omitted rows, the old producer revision or Yahoo quote units.

A fresh bounded broker read of 2025-10-08..2026-10-08 returned three executions,
88 cash movements and 88 rows from the alternate authenticated CSV-report endpoint.
Ten dividend/withholding pairs remained uniquely associated. Count agreement and
that alternate API export do not prove an independent manual statement or unlimited
history. `history_completeness_verified` remains false.

An offline comparison of those three recent executions with the same saved
destination found one financial candidate for each: same broker-local calendar
day, BUY/SELL side, absolute quantity, unit price and activity currency. The
candidate profile currencies also agree with the broker currencies (two JPY,
one USD). However, all 29 distinct target asset profiles lack an ISIN, so this
does not establish an independent instrument mapping. A broker ticker matches
one target symbol for the USD candidate; ticker equality is not adopted as proof.

Using each candidate symbol only as an explicitly unverified placeholder, the
source arithmetic reproduces the candidate price and quantity but not its fee:
all three existing fees differ from the API total brokerage-plus-AutoFX fee
converted into the security currency. The timestamps differ as well; source
minus target is approximately -30,997, -26,086 and -1,093 seconds. These are
recorded mismatches, not a diagnosed timezone correction or permitted tolerance.
Comments are not canonical API execution identities. Do not infer missing trades
from a failed ISIN join, infer instrument identity from matching financial values,
adopt these candidates or rewrite their fees/dates automatically. Original input
hashes were unchanged and the comparison used no network or financial callbacks.

Before the cash-yield policy implementation, the recent ledger contained four
Flatex interest rows and one monetary-fund compensation row. Dividend
normalization and current-cash acceptance both stopped
at the unsupported-category gate. No successful real synchronization DRY_RUN or
cash acceptance is claimed. Do not discard these rows, fabricate completeness,
borrow a quote-unit mapping, or clear uncertain state to make the preflight pass.
A subsequent direct collection requested 2000-01-01..2026-10-08 and reread the
occupied span with different window widths. Both yielded identical complete bodies
for 70 executions and 1,001 nonzero-ID cash events, plus an identical full CSV.
Legacy monetary-fund NAV rows instead use ID `0` and differ between window widths.
Exact statement comparison also exposes zero-valued CSV-only NAV rows, one-cent
amount differences and changed descriptions. Private raw windows and manifests
stay outside GitHub; these gaps do not become a history override.

Evidenced treatment of remaining historical rows, scoped full-statement
reconciliation and source-bound destination transition remain prerequisites. See [the source contract](source-contract.md),
[synchronization](synchronization.md) and [isolated acceptance limits](isolated-acceptance.md).

## Saved-input verification after cash-yield implementation (2026-10-09)

Offline analysis using adapter revision `5966e121ca2465fffbe68f9ae52216504c0d9066`
rechecked the retained source and destination captures. Network access was disabled,
no financial callbacks ran, and all source-file hashes remained unchanged.
The complete 1,017-row destination response still passed ownership/context checks.
The recent 88-row source had no unsupported category: ten dividend pairs, five
cash-yield activities and three standalone fees normalized independently. Current
cash validated using the source capture's own timestamp as `now`; this establishes
capture-time compatibility, not present freshness or a successful whole-account run.

Comparing date, local minute, value date, source ISIN, description, currency,
amount and order reference as multisets matched 87 of 88 recent CSV rows exactly.
The sole remaining pair is a `TRANSACTION` with a one-cent amount difference;
all other compared fields agree. No rounding tolerance or financial correction
was applied. Minute equality does not establish payment association or canonical
activity identity. The CSV is the captured broker report, not a newly supplied
independent manual statement.

Annual and split archives contain 70 identical stable executions and 1,001
identical nonzero-ID cash-event bodies, with byte-identical CSV reports. Earlier
comparisons used partially merged diagnostic snapshots, whose extra retained
rows made their counts unsuitable as authoritative reconciliation evidence.
The raw-response comparison below supersedes those snapshot counts. Both archives
fail the legacy-cash format gate and retain unverified history; neither can be
substituted for an accepted source snapshot or prove completeness.

The category-policy obstacle is resolved for the characterized yield rows.
Subsequent independent public Yahoo ISIN search and chart metadata verification
established an eight-instrument mapping, retained privately with its evidence.
Exact CSV transition semantics and history proof remain distinct prerequisites.
No broker-ticker fallback, completeness flag or production-write authorization
was introduced.

## Recomputed raw-input reconciliation (2026-10-09)

The offline [saved-input diagnostic](../scripts/reconcile_saved.py) compares the
retained recent source, full destination and verified eight-ISIN mapping. It also
rereads both raw window archives and the captured statement. It binds 151 input
files plus four implementation files by SHA256, verifies them unchanged before
publishing a new mode `0600` YAML report and disables network access. It has no broker login, HTTP client, adoption,
cleanup or journal-confirmation operation. Private rows, created IDs, symbols
and amounts are retained only in the ignored report.

Raw bodies are compared after removing only derived cash `balance`. Every body
retains its response path, requested dates and row index, including duplicate
occurrences. Unique-body counts describe observations, **not an authoritative
merged ledger**. The exact comparison preserves multiplicity between distinct
source bodies and dated statement rows, with no rounding tolerance.

| Raw comparison | Annual windows | Split windows |
| --- | ---: | ---: |
| Unique cash bodies | 1,340 | 1,319 |
| Exact eight-column statement matches | 1,334 | 1,314 |
| API bodies without an exact statement row | 6 | 5 |
| Dated statement rows without an exact API body | 29 | 49 |
| Description-only continuation lines, retained separately | 3 | 3 |
| Responses missing their cash collection, not proved empty | 19 | 0 |

Both byte-identical statements have 1,366 post-header lines: 1,363 dated rows and
three description-only continuation lines. A separate comparator using Decimal
JSON decoding independently reproduced both sets of counts. The common 1,001
nonzero-ID cash bodies and 70 execution bodies agree exactly across widths.
NAV remains window-dependent: 339 annual/318 split unique bodies, with 150
annual-only and 129 split-only bodies. All are ID zero. Missing collections and
the diagnostic counts do not establish account inception or complete coverage.

Residual discrepancies have distinct explanations and limits:

- Three exact date/minute/value-date/ISIN/order candidates differ only in
  description. Each following description-only CSV line completes the API
  description. The report retains them separately; it does not concatenate
  descriptions or approve a new semantic normalization rule.
- Two execution cash amounts differ by one cent from their statement counterparts.
  Exact quantity-times-price arithmetic lands on half-cent ties. In the recent
  case the API amount agrees with half-up and the CSV with half-even. In the older
  case half-up and half-even agree with the CSV while the API rounds toward zero.
  These observations do not prove a universal broker rule or authorize an epsilon.
  Execution totals retain their unrounded precision.
- Annual comparison has one additional NAV amount discrepancy. CSV-only NAV
  candidates total 24 in annual comparison (22 zero, two nonzero) and 44 in split
  comparison (20 zero, 24 nonzero). These counts include the annual amount-mismatch
  counterpart. Their financial treatment remains unproved; zero values remain too.

The 70 raw executions have the same first-failure diagnostic in both archives:
eight normalize independently under the saved verified mapping, 55 first stop
at absent verified mapping, three at unsupported transfers, three at invalid FX
and one at a missing/invalid financial value. A first failure can hide additional
contract gaps. Per-row conversion is diagnostic only: it does not relax the
full-history import-format or whole-account gates.

The recent 88-row source still has 87 exact statement matches and the one
half-cent case. Conversion produces three SELL, ten DIVIDEND, three FEE and
five INTEREST candidates. Against the complete saved destination:

- Each SELL has exactly one same-symbol/provider/currency/broker-local-day
  candidate with equal quantity and price, but different fee, instant and comment.
  One candidate's fee agrees only after cent rounding; there is no precision waiver.
- Seven dividends have exactly one such candidate with equal quantity, gross
  payment and withholding, but different instant and comment. Three winter
  candidates are approximately one hour later; four summer candidates agree only
  at UTC-minute precision. Unknown producer provenance prevents a timezone policy.
- Three dividends have no such candidate; there is also no target DIVIDEND on
  each corresponding UTC date. This is a bounded absence observation, not proof
  of a missing historical payment or permission to insert it.
- Three fees and five yield candidates have no same-symbol/type/day candidate.
  Missing candidates do not establish that their economics are absent elsewhere.

The full adapter replay at the original source capture time refuses with
`Manual or CSV activity requires explicit reconciliation`. Both financial
callbacks are forbidden; none is invoked. No snapshot, mapping, journal or
production state changes. This replay proves capture-time behavior, not a fresh
real DRY_RUN or current cash. C14 remains open pending the separate
[historical contracts](plans/history-contract-extension.md) and transition evidence;
this diagnostic implements none of those proposed exceptions.

### Reproduction and rollback

Use the canonical project virtualenv and existing private files. The target file
contains only the exact destination account ID; it is private input too.

```sh
.venv/bin/python scripts/reconcile_saved.py \
  --source /private/recent-source.json \
  --destination /private/ghostfolio-snapshot.json \
  --mapping /private/verified-mapping.yaml \
  --target-id-file /private/target-account.txt \
  --archive /private/annual-archive \
  --archive /private/split-archive \
  --output tmp/reads/new-reconciliation.yaml
```

Each archive requires original `window-NNN.json`, `account-statement.csv` and
`history-annual.json` or `history-split.json`. Snapshot product metadata supplies
ISINs; its cash/trade arrays are not used as trusted merged history. The tool
accepts only the observed 12-column French statement header. Unknown shapes fail
instead of silently skipping rows. Archives are optional; the complete saved
destination and mapping remain mandatory. Output must have an existing parent,
be outside the repository or under ignored `tmp/`, and be new. Existing files,
input aliases and direct symlinks are refused. Standard output contains counts
only. A report is not an adoption manifest or complete-history proof.

Blast radius is offline diagnostics and aggregate documentation. Revert the exact
diagnostic commit to remove the tool and report update; retain original archives,
private reports and unresolved journals. No financial or service rollback applies.
