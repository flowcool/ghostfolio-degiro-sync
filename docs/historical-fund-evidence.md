# Historical fund evidence and remaining reconciliation boundaries

This read-only characterization extends the retained evidence on 2026-10-10.
It approves no historical importer, product alias, CSV adoption, financial
tolerance, cleanup or deployment. The approved delivery plan and the separately
proposed [historical contracts](plans/history-contract-extension.md) remain the
policy boundaries. Beads owns acceptance and execution state; this document is
evidence, not a task queue or a completion declaration.

## Raw inputs and method

The original annual and split broker responses, their byte-identical captured
CSV statements and captured product metadata remain private. Diagnostics verify
all 155 previously bound input files before and after analysis. Additional raw
reads and report dependencies are hash-bound too. JSON numbers are decoded with
Decimal; original response paths, requested dates and row occurrences are
retained. Each new private YAML report is created exclusively with mode0600.
There are no broker sessions, network requests, financial callbacks or changes
to the adapter, source captures, mapping or write journal.

Both response widths still agree on 1,001 nonzero-ID cash bodies, including 62
fund-conversion bodies, and 70 executions. Only derived cash `balance` is
excluded from exact body comparisons. Unique bodies and comparison envelopes
are diagnostics, not authoritative merged ledgers. See the earlier
[saved-input reconciliation](readonly-reconciliation.md) for the complete
comparison contract and its limits.

## NAV product attribution and residual rows

| Comparison | Result |
| --- | ---: |
| Unique annual / split NAV bodies | 339 / 318 |
| Exact common complete NAV bodies | 189 |
| Additional one-to-one pairs differing only in `productId` | 116 |
| Common bodies when omitting only `productId` diagnostically | 305 |
| Residual annual-only / split-only bodies under that comparison | 34 / 13 |

The two captured product records for every additional pair carry the same
nonempty ISIN. Removing `productId` causes no within-archive body collision.
Removing any other single field does not increase the 189 exact matches.
Thus some window-dependent differences concern product attribution. Captured
share-class identity does not establish broker event identity, historical
metadata continuity or a permissible runtime deduplication rule.

Of the 34 annual residuals, 33 match the captured statement exactly and one has
an amount-only statement candidate. All 13 split residuals match exactly. The
annual set contains ten zero and 24 nonzero amounts; the split set contains
twelve zero and one nonzero amount. Only one residual occurrence is at a
requested-date boundary; 46 are interior. Dropping boundary days would not
explain the observed differences.

The maximum per-key multiset across the two NAV display projections contains
352 rows, with 305 common keys. Against the 362 statement rows carrying an
observed NAV description, 351 match exactly. Eleven statement rows remain
outside this observation envelope: ten zero rows and one nonzero row with an
amount-only projection candidate. One projection amount lacks an exact
statement counterpart. No zero row is discarded, amount discrepancy tolerated
or maximum multiset adopted as historical truth.

These comparisons use all eight previously defined statement columns and retain
multiplicity. Exact display keys include the captured ISIN but not internal
`productId`; matching display keys do not authorize activity identity. The CSV
was obtained from the authenticated broker report endpoint and is not an
independently supplied manual statement or account-inception proof.

## Fund conversion descriptions and units

All 62 stable fund bodies contain the characterized French description form
`Conversion Fonds Monétaires finalisée: Achat|Vente <quantity> @ <price> EUR`.
Quantity uses a decimal comma; 60 prices use comma decimals and narrow no-break
thousands separators, while two prices are literal zero. Parsing this exact
observed form yields 30 BUY and 32 SELL description candidates. This is source
characterization, not a new adapter conversion rule.

Only three bodies have a nonzero `change`; the other 59 lack that field. None of
the three recorded changes equals the signed quantity-times-price principal
candidate. The absence of `change` cannot become a zero cash movement, and a
description's gross product cannot become an implied API cash flow or fee.

The two zero-price descriptions have opposite sides, equal described quantities,
different product IDs and exactly cancelling recorded changes at the same
instant. Their values are retained as unresolved evidence. Those relations do
not authorize free purchases, zero-value sales or an inferred corporate action.

Sixty-one fund rows have one exact statement match. One has no exact match and
two description-only candidates; it remains ambiguous. Summing signed described
units under the single captured ISIN ends at zero, but one completed timestamp
group produces a negative cumulative quantity smaller than 0.001. No quantity
tolerance, rounding explanation, opening position or full-history claim follows.

All 62 current product records point to the ISIN identified in the official
Morgan Stanley KIID below. Eleven source rows precede that document's stated
fund launch date. The issuer mentions a transfer from an equivalent predecessor
fund, but supplies no predecessor ISIN in the inspected KIID. Current metadata
therefore cannot alone establish the historical share class or basis.

## Statement balance arithmetic

A separate diagnostic preserves the received row ordering and compares each
dated row with the next older reported balance in the same currency. Across
1,363 dated rows there are 1,090 exact amount/delta equations, 84 mismatches,
184 absent movement amounts and five rows without an older same-currency
balance. Among the 362 NAV-described rows, 280 equations agree and 82 do not.

No chronology decrease was observed at the CSV's minute precision. That does
not prove ordering within a minute. These are reported-balance comparisons,
not a validated ledger: no opening balance, FX conversion, rounding exception,
blank-means-zero rule or claim of a broken broker statement is introduced.
The mismatches cannot be silently used to equate fund valuation, cash flow and
portfolio return.

## Primary public framework

- [DEGIRO Services de placement](https://www.degiro.fr/data/pdf/fr/PSP_Services_de_placement.pdf),
  dated 2022-08-30, page8 §3.1: automatic investment of receipts in fund units
  and fluctuations of fund value are distinct mechanisms. This later document
  does not classify an individual historical API row.
- [DEGIRO Investment Services Conditions](https://www.degiro.ch/data/pdf/fr/Conditions_Services_De_Placement.pdf),
  dated 2022-08-30, articles10.1.2/10.2.1: fund units can be redeemed to meet
  obligations or withdrawals. Articles10.1.1/10.3.3 describe account-specific
  replacement with cash accounts and transfer of sale proceeds. They establish
  no universal migration cutoff or account-level opening balance.
- [Morgan Stanley Euro Liquidity Fund KIID](https://www.degiro.fr/data/pdf/fr/Morgan%20Stanley%20Euro%20Liquidity%20Fund%20%28Fran%C3%A7ais%29.pdf),
  current as of 2021-02-18, Qualified Accumulation D, EUR, ISIN LU1959429272:
  income accumulates in unit value; negative net income can reduce that value.
  The class launched in2019 and the fund on2019-06-14 after an equivalent
  Morgan Stanley Funds p.l.c. asset transfer. This is exact-share-class evidence,
  not proof of predecessor continuity or an API NAV contract.
- [DEGIRO Participations](https://www.degiro.fr/data/pdf/fr/PSP_Participations.pdf),
  dated2022-03-30: FundShare and Morgan Stanley money-market funds are listed.
  The inspected FundShare issuer link is unavailable; its redirected general
  site was not accepted as an official historical share-class source.

The four retained public PDF SHA256 values, in the same order, are:

```text
services      2c690410e43f9613a5c778518a32c540bd55d9b035a3fc2645ca44384c4c4786
conditions    ffcbff9d4387e134ef033c15e735b2996509afcc591be2c6f1a0cdd74401a39b
KIID          282029b1f0cc6ac80193f2080f26c5a4046741353e360b382489921f918d9028
participation 8f428636be5871269f19b5188f9f5d595b8615a294ca2223bc151c54ec225193
```

None defines `CASH_FUND_NAV_CHANGE`, zero IDs, query-window projections,
statement rounding or product-ID continuity. Accumulation evidence does not
justify paid INTEREST/DIVIDEND activities for NAV changes. No compensation
eligibility or per-NAV allocation was established; the existing
[adopted compensation convention](interest-compensation-policy.md) is unchanged.

## Concrete evidence needed for a historical contract

1. Source-bound subscription/redemption confirmations with quantities, prices,
   fees, currency and historical product/class identity, including the two
   zero-price records and the ambiguous statement association.
2. Predecessor/successor conversion notice and a broker-backed disposition of
   the three recorded changes that differ from described principal arithmetic.
3. A broker-authored NAV/statement projection contract, or independently
   reconciled fund-unit and valuation observations for the exact period. It must
   account for the ten absent zero rows and the remaining amount difference.
4. Bounded account-inception/opening positions and statement coverage, then
   source-bound dispositions for the other legacy execution, tax, FX and
   destination-transition gaps already identified in the historical proposal.

These are distinct from choosing a financial reporting representation. Even a
proved accumulation share class does not decide whether native fund activities,
cash valuation evidence or another representation preserve the account's
economics. Any eventual contract requires its separate approved scope and
synthetic/native proof. This document provides no override or completeness flag.

## Verification and rollback

Private reports are `nav-residual-statement-evidence-20261010.yaml`,
`nav-statement-envelope-20261010.yaml`,
`statement-balance-equations-20261010.yaml` and
`fund-description-unit-evidence-20261010.yaml`, under ignored `tmp/reads/`.
The deterministic scripts, input digests, exact observations and caveats are
retained privately; only aggregate findings appear here. Original source files
are unchanged. Public document dates, clauses, exact share class and SHA256 were
checked against retained PDFs and local text extraction.

Blast radius is documentation and private offline analysis. Revert the exact
documentation commit to undo the versioned change; preserve original captures
and unresolved journals. No service, financial or account rollback applies.
