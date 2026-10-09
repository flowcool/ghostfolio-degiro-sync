# Interest and monetary-fund compensation: adopted reporting policy

This document records the accounting arbitration delegated by Florent on
2026-10-09. Zero Flatex interest will be retained as zero INTEREST activities;
positive monetary-fund compensation will use INTEREST as a cash-yield reporting
convention, with a distinct source identity and symbol. The adapter supports
only the observed EUR contract below, including identity, readback and recovery.
Uncharacterized amounts, relations, currencies and source fields block writes. Legacy NAV/fund history remains a separate
contract; production writes, cleanup and deployment are not authorized.

## Broker evidence

The privately retained original annual API windows contain 16 Flatex Interest
Income rows, all zero EUR, and one positive EUR monetary-fund compensation row.
Every selected row has a stable nonzero cash ID, `type`, description, currency,
change, offset timestamp and value date. None has a product ID, order ID or
exchange-rate field. Repeated identities agree after removing only the previously
characterized window-derived balance.

The full authenticated broker CSV independently agrees with both selected
multisets on local date/minute, value date, description, currency and amount:
16 interest rows and one compensation row. This establishes those recorded
movements; CSV minute precision does not replace API timestamps or identities.
No positive interest, negative interest, withholding relationship or compensation
product attribution has been characterized. The label and amount alone do not
establish tax treatment, contractual bank interest, a security dividend, fee
refund or product-level NAV allocation.
Private amounts, account identities and input rows are not published here.

## Decision evidence and limits

Florent supplied an explanation that compensation offsets negative yield on
cash held in money-market funds, rather than brokerage fees or margin debit
interest, and delegated the reporting choice. The official
[DEGIRO Investment Services Conditions](https://www.degiro.ch/data/pdf/fr/Conditions_Services_De_Placement.pdf)
(articles 10.1.2 and 10.2.1, PDF page 24) confirm standing instructions to invest
client cash in money-market funds for clients offered and choosing that option. Articles 10.1.1 and 10.3.3 describe their gradual replacement
with bank cash accounts. The official
[money-market fund document page](https://www.degiro.fr/helpdesk/documents/fonds-monetaires)
links [Participations, dated 2022-03-30](https://www.degiro.fr/data/pdf/fr/PSP_Participations.pdf),
which identifies the funds. Neither inspected document describes compensation
eligibility or explicitly qualifies the account's credit.

The economic explanation is operator-supplied; the MMF framework, actual credit
and native representation are independently checked. This is sufficient for an
explicit engineering reporting convention, without presenting the compensation
as legally or fiscally established interest. Use INTEREST because Ghostfolio can
record a cash-yield receipt without treating it as an external contribution or
inventing a dividend security. Preserve a distinct compensation label and identity
so future reclassification remains reviewable. Do not encode approximate policy
dates, thresholds, quarterly frequency or a relationship to individual NAV rows.

## Pinned native representation

Ghostfolio 3.81.0 source commit
`920d0787541a8568920fc11f978aa01e5a52c581` establishes:

- [Type and DTO](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/libs/common/src/lib/dtos/create-order.dto.ts):
  `INTEREST` accepts nonnegative quantity, unit price and fee. Negative refunds
  or reversals cannot be represented by negating these fields.
- [Import](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/apps/api/src/app/import/import.service.ts):
  explicit MANUAL symbols must be UUIDs or use the `GF_` prefix. Native duplicate
  matching includes comment and financial fields but omits target account ID.
  Import creation explicitly disables account-balance updates.
- [Creation](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/apps/api/src/app/activities/activities.service.ts):
  non-investment activities use MANUAL profiles. Returned custom symbols must
  still be verified; descriptions do not become canonical identifiers.
- [Account totals](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/apps/api/src/app/portfolio/portfolio.service.ts)
  accumulate interest as quantity times unit price, converted into the user's
  base currency. Account currency alone does not establish aggregate currency.

These are source findings, not a claim that upstream tests were executed here.

## Disposable native proof

Run the separate operator characterization, never pytest against a real server:

```sh
.venv/bin/python scripts/check_interest_contract.py
```

The script accepts no target URL or operator credentials. It creates a UUID-owned
Compose project using the pinned Ghostfolio/Postgres/Redis images from the existing
isolated acceptance harness. It requires pre-existing images (`--pull never`), an
internal network, no published ports or host binds and a fresh tmpfs database.
It verifies empty native activity storage before creating a disposable user and
account. Authentication stays in memory. Only the synthetic user's base-currency
setting is changed to EUR; no production or broker connection is made.

Observed on 2026-10-09 at Ghostfolio image digest
`sha256:7c925671dba267cc2175195f064b42b9733f3ea170a21db488b7d2be3319e088`:

| Probe | Result |
| --- | --- |
| Immutable core DRY_RUN | Proposal returned; zero stored activities |
| Native import preview | Positive and zero INTEREST accepted; zero stored activities |
| Native import + immutable core evidence | EUR 10 and EUR 0, quantity 1, fee 0, exact account/comment/date/custom symbol/type |
| Identical repeat | Zero new activities |
| Negative quantity, unit price or fee | Each preview HTTP 400; stored count unchanged |
| Same instant and amount, different cash-event comment | One distinct new activity |
| Full account readback | Three activities; interest total EUR 20; account cash remains EUR 0 |

Both successful and failed runs attempt independent bounded cleanup of owned
containers and the internal network. Failed teardown retains a private nonsecret
ownership record for explicit recovery; catchable termination uses the same path.
SIGKILL cannot guarantee cleanup. See the [lab recovery procedure](isolated-acceptance.md#cleanup-and-rollback-preflight).
The database is temporary; no shared image is deleted. Offline tests verify
changed financial readback and aggregate rejection, credential-log privacy,
explicit EUR aggregate context and rejection of foreign/exposed container state.
Isolation and result checks remain active with Python optimization enabled;
every Compose command explicitly pins the generated project name with `-p`.
Stored GET rows are checked individually through immutable-core financial/date
evidence, independently of listing order and aggregate totals.
This proves native representability, not the unobserved positive broker contract.

## Adopted decision boundaries

| Source case | Adopted treatment | Remaining implementation evidence |
| --- | --- | --- |
| Zero Flatex interest | Retain an INTEREST/MANUAL activity, quantity 1, unit price 0, fee 0 | Exact source identity, target ownership and repeat readback; zero rows must remain accounted for |
| Positive Flatex interest | Remain blocked until broker gross/net, tax relationship and currency are characterized | An actual paid broker row and statement; synthetic native support is insufficient |
| Negative interest, reversal or refund | Remain blocked | Explicit signed-accounting/reversal representation; no negated DTO values, clamping or unrelated FEE |
| Positive monetary-fund compensation | INTEREST/MANUAL as a reporting convention, quantity 1, credited amount as unit price, fee 0 | Exact cash credit and independent CSV agreement, distinct compensation identity/label, native readback and aggregate reconciliation |
| Zero or negative compensation, corrections | Remain blocked | A characterized contract and exact representation; no broad sign-based category rule |

Identity design for implementation:

- Zero Flatex interest: `DEGIRO#<source-account>:INTEREST:<stable-cash-id>`,
  MANUAL symbol `GF_DEGIRO_<source-account>_FLATEX_INTEREST_<currency>`.
- Positive compensation: `DEGIRO#<source-account>:COMPENSATION:<stable-cash-id>`,
  MANUAL symbol `GF_DEGIRO_<source-account>_MMF_COMPENSATION_<currency>` and
  descriptive symbol identifying DEGIRO money-market fund compensation.

These are supported runtime identities. Target account must participate in ownership and duplicate
validation; separate same-day events remain separate. Preserve the cash amount
and currency without implicit FX or scaling. For compensation the stored amount
is the observed credit; fee 0 means no fee is attached to that activity and does
not assert the absence of separate fees or tax. Do not invent gross amounts or
withholding. Separately observed taxes, charges or corrections need their own
relationships and must block if unsupported. Native import must not increment
account cash, which is set only from the independently verified final snapshot.
Missing or ambiguous source or readback evidence blocks the whole account.

The adapter accepts these INTEREST and COMPENSATION identities with exact
EUR/MANUAL symbols, quantity 1 and fee 0. Canonical zero-interest amounts must
stay zero; compensation amounts must stay positive. Manual/CSV INTEREST near a
candidate blocks regardless of its custom symbol, requiring explicit reconciliation.
Cleanup preflight and uncertain-import recovery use the same exact identity/readback
checks; cleanup still performs no deletion. This work belongs in the adapter; the immutable core must not
be forked. Native support alone cannot relax the full-history or unsupported
category gates. Current cash is a separately validated final snapshot, not a sum
of these movements; native import must not also credit the account balance.

## Approval, validation and rollback

Adopted on 2026-10-09 under Florent's delegated accounting arbitration, revised
following his supplied economic explanation and official framework sources.
The [README](../README.md#accounting-policy-preserve-cash-yield-and-source-identity)
states the rationale. No further operator accounting choice is a prerequisite
for this bounded representation. The implemented rules admit only zero EUR
Flatex interest and positive cent-valued EUR compensation. Strict source field
checks reject unexpected product, order, FX, tax or other financial relationships.
Whole-account rejection regressions continue for every uncharacterized case.

Verification covers synthetic conversion, source/target ownership,
same-day distinct identities, mixed currency, negative/correction refusal,
repeat-zero behavior and uncertain-request fencing, then isolated native adapter
acceptance and private source/CSV reconciliation. Selected private annual/split
conversion signatures agree for all 17 events (16 zero interest and one positive
compensation); the complete CSV independently matches their date/minute, value
date, description, currency and amount multiset. This selected-event proof does
not establish full-account C13-C14 acceptance. Legacy NAV
identity and CSV-transition completeness remain separately enforced.

Observed adapter acceptance on 2026-10-09 using the pinned Ghostfolio image
above and the owned runtime image manifest
`sha256:095ff45d1a730a1cd9f0e9a3b2b0a0021527607b1838086b9c1aebba8fdb81fd`:

- Dry-run retained all three synthetic events and created no activities.
- Two equal compensation credits at the same second remained distinct; zero
  interest was stored with quantity 1 and price 0. Exact financial/date/symbol
  readback and cleanup ownership matched the candidate manifest.
- Repeat created zero activities and preserved exact created IDs and financial
  signatures. Account-write metadata is compared separately from financial data.
- Interest totals were EUR 5 then EUR 7.5 after one further compensation; the
  independently set cash balance stayed EUR 12.30 without adding receipt amounts.
- Negative compensation and nonzero Flatex interest changed no activity or cash.
- A lost reply after native insertion fenced a fresh process; exact selected
  request readback resolved the journal, and repeat created nothing.
- Existing native trade/dividend/fee, CSV overlap, partial cancellation and cash
  uncertainty scenarios passed. Owned containers, network and fixture images were
  removed; no production endpoint, credential or database was used.

Rollback of this characterization is a scoped Git revert. Lab rollback uses
`scripts/lab_cleanup.py --recover <private-ownership-record>` when automatic
teardown is incomplete. The temporary authentication manifest is removed;
recovery independently revalidates exact resource IDs and UUID project labels. Keep broker archives
and unresolved write journals intact. No live financial rollback, production
interruption or deployment is part of this proposal.
