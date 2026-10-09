# Interest and monetary-fund compensation: policy proposal

This document prepares the accounting decision owned by `infra-8tt.56.14`.
It does not approve new importer support. The current `cash-rules.yaml` entries
remain `unsupported_blocking`, including zero interest. The approved delivery
scope and gates C1-C15 remain unchanged; legacy NAV/fund history has a separate
future owner. Production writes, cleanup and deployment are not authorized.

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
product attribution has been characterized. A compensation label and a positive
amount do not prove interest, security dividend, fee refund or NAV treatment.
Private amounts, account identities and input rows are not published here.

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

Both successful and failed runs remove only their owned containers and network.
The database is temporary; no shared image is deleted. Offline tests verify
changed financial readback and aggregate rejection, credential-log privacy,
explicit EUR aggregate context and rejection of foreign/exposed container state.
This proves native representability, not the unobserved positive broker contract.

## Proposed decision boundaries

| Source case | Candidate future treatment | Evidence or decision still required |
| --- | --- | --- |
| Zero Flatex interest | Preserve a zero INTEREST activity with quantity 1; alternatively retain an explicitly accounted-for cash-only notice | Florent chooses the zero-event policy; an activity needs adapter identity/context/readback integration, a notice needs auditable source accounting and must not disappear silently |
| Positive Flatex interest | INTEREST/MANUAL, quantity 1, gross amount as unit price; fee zero only when independently proved | Actual paid broker row and statement must establish gross/net amount, tax relationship and currency; native synthetic acceptance alone is insufficient |
| Negative interest, reversal or refund | Remain blocked | Explicit signed-accounting/reversal representation; no negated DTO values, clamping or conversion to an unrelated FEE |
| Monetary-fund compensation | Remain blocked | Broker documentation or source-bound statement proof of economic meaning; no automatic INTEREST/DIVIDEND/FEE classification from label or sign |

For future INTEREST activities, a candidate canonical comment is
`DEGIRO#<source-account>:INTEREST:<stable-cash-id>` and a candidate MANUAL symbol
is `GF_DEGIRO_<source-account>_FLATEX_INTEREST_EUR`. These are design examples,
not current supported identities. Target account must participate in ownership
and duplicate validation; separate same-day rows must remain separate.
Source amounts/currency must be preserved without implicit FX or price scaling.
Fees, withholding and reversals need their own exact relationships. Missing or
ambiguous evidence blocks the whole account.

The adapter currently rejects target INTEREST types and canonical INTEREST
comments. Both boundaries, broker conversion, uncertain-import recovery,
manual/CSV overlap, cleanup ownership and repeat readback must be tested before
enabling a policy. This work belongs in the adapter; the immutable core must not
be forked. Native support alone cannot relax the full-history or unsupported
category gates. Current cash is a separately validated final snapshot, not a sum
of these movements; native import must not also credit the account balance.

## Approval, validation and rollback

Recommended decision now: retain both existing blocks. The native experiment
makes a bounded future zero/positive-interest proposal reviewable; compensation
still has no proved accounting representation. Florent's current-scope decision
does not authorize implementing either proposal. Approval is required before
changing rules, adapter behavior or introducing an explicit cash-only exception.

After a policy is approved, its owning issue must prove synthetic conversion,
exact source/target ownership, same-day distinct identities, mixed currency,
refund/reversal refusal, repeat zero and uncertain-request fencing, then isolated
native acceptance and private source/statement reconciliation. Native-contract
proof above does not close those future integration criteria or C13-C14.

Rollback of this characterization is a scoped Git revert. Lab rollback is
`docker compose down` for the exact temporary Compose file created by the script;
the `finally` path performs it before deleting that file. Keep broker archives
and unresolved write journals intact. No live financial rollback, production
interruption or deployment is part of this proposal.
