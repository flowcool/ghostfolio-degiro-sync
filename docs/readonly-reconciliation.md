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

An explicitly approved policy for unsupported rows, scoped full-statement
reconciliation and explicit request-bound cash/partial recovery remain prerequisites. See [the source contract](source-contract.md),
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

Annual and split archives still contain 70 identical stable executions and 1,001
identical nonzero-ID cash-event bodies, with byte-identical CSV reports. The annual
archive contains 1,377 cash rows including 340 zero-ID rows; the split archive has
1,326 cash rows including 319 zero-ID rows. Their respective exact CSV multiset
matches are 1,254 and 1,231 of 1,366 CSV rows. Both fail the legacy-cash format gate
and both retain unverified history. These characterization-only archives cannot
be substituted for an accepted source snapshot or prove completeness.

The category-policy obstacle is resolved for the characterized yield rows;
verified ISIN-to-Yahoo quote mapping, exact CSV transition semantics and history
proof remain distinct prerequisites. No broker-ticker fallback, inferred mapping,
completeness flag or production-write authorization was introduced.
