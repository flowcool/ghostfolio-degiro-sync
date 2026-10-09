# Proposed historical contract extension

Florent authorized this specification on 2026-10-09, not its implementation.
The approved delivery plan and C1-C15 remain unchanged. Publishing or merging
this document does not approve a historical importer, CSV adoption, a financial
correction, cleanup or deployment. Beads owns execution and acceptance state.

## Problem and decision

**NO-GO for full-history import on the retained evidence.** Stable executions and
cash events can support characterization, but cannot establish the semantics of
window-dependent fund projections, missing tax relations or legacy trade fields.
Recommend evidence-first, separately approved contract extensions. Keep the
whole-account refusal until every relevant event has an evidenced treatment.

Do not reopen the adopted [cash-yield policy](../interest-compensation-policy.md):
zero EUR Flatex interest and positive cent-valued EUR compensation already have
distinct INTEREST/MANUAL representations. That convention establishes neither
NAV accounting nor positive interest, tax refunds or signed reversals.

An arbitrary start date is not a safe shortcut. It requires independently proved
opening security quantities, basis/fees and balances, with an explicit treatment
of existing destination history. Synthetic opening BUYs or a historical balance
substituted for current cash are not proposed.

## Evidence and its limits

The [source contract](../source-contract.md) and
[saved-input reconciliation](../readonly-reconciliation.md) are the aggregate
sources. Private rows, account identifiers, holdings and amounts stay outside Git.
Rechecking original archived window responses on 2026-10-09, removing **only**
the already characterized derived `balance`, gives:

| Evidence | Observed result | What it does not prove |
| --- | --- | --- |
| Stable cash bodies | 1,001 identical nonzero-ID bodies across annual/split reads, including 62 fund transactions | Stable identity is not a supported fund accounting model |
| NAV projections | 339 distinct annual bodies, 318 split; 150 annual-only and 129 split-only, all ID zero | No independent event identity or deduplicable complete NAV history |
| Executions | 70 complete bodies agree across widths | Full account inception, units, side/sign and missing-field semantics |
| Dividend/tax groups | 95 exact unique pairs; remaining payments/taxes include time offsets, missing/multiple tax and positive adjustments | Same-minute statement agreement is not a payment relationship |
| Statement | Identical captured CSV bytes across reads; financial, description and zero-NAV discrepancies remain | An independent manually retained statement or a reconciled ledger |
| Recent mapped source | Eight instruments verified through public Yahoo ISIN search and quote metadata; three trades and ten dividends normalize | Existing CSV/manual entries are not adopted; complete DRY_RUN still refuses reconciliation |

Raw unique bodies above are not merged diagnostic-snapshot row counts: a failed
merge can retain extra rows. Preserve response provenance and multiplicity before
comparing or deriving any authoritative ledger. Hash checks verified that this
specification's archive inspection did not modify its inputs.

## Proposed decision contracts

These keyed records describe approval gates, not runtime configuration. Each
`future_owner` names exactly one proposed deliverable; implementation issues are
created only after explicit scope approval. End-to-end acceptance remains solely
owned by `infra-8tt.56.11`; production authorization by `infra-8tt.56.12`.

```yaml
format: 1
runtime_enabled: false
contracts:
  fund_transactions:
    future_owner: H1_fund_event_contract
    default: block
    prerequisite: source-bound units, security identity, principal flow and cash relationship
    forbidden: map fund purchases or sales to STOCK, DIVIDEND, FEE or external funding by label
  nav_projections:
    future_owner: H1_nav_reconciliation_contract
    default: block
    candidate: retain as reconciliation evidence, not independently imported activities
    prerequisite: prove valuation period and fund-principal relationship without lost cash or return
    forbidden: invent broker IDs, collapse by ID zero, drop changes, sum overlapping projections
  offset_withholding:
    future_owner: H2_payment_link_contract
    default: block
    prerequisite: independent source-bound payment link and unique one-to-one association
    forbidden: nearest timestamp, same day or minute alone, sum ambiguous candidates
  untaxed_dividends:
    future_owner: H2_untaxed_payment_contract
    default: block
    prerequisite: explicit zero-tax or exemption evidence, gross/net meaning and quote units
    forbidden: infer fee zero from absent withholding
  tax_adjustments:
    future_owner: H2_signed_adjustment_contract
    default: block
    prerequisite: original-event relation and independently tested signed accounting representation
    forbidden: negative DTO fees, absolute values, clamp to zero, unrelated positive income
  legacy_execution_fields:
    future_owner: H3_execution_field_contract
    default: block
    prerequisite: independent reconstruction of quantity, totals, commission, AutoFX and base conversion
    forbidden: missing means zero, zero FX means one, use net FX to reapply fees
  additional_quote_units:
    future_owner: H3_quote_unit_contract
    default: block
    prerequisite: independently verified ISIN, listing, Yahoo quote currency and unit scale
    forbidden: broker ticker fallback, copy another broker unit rule, implicit FX or 100x scaling
  transfers_and_actions:
    future_owner: H3_transfer_action_contract
    default: block
    prerequisite: explicit quantity and basis model with source and destination legs
    forbidden: synthetic executions, invented proceeds, use cash to hide missing basis
  csv_transition:
    future_owner: H4_source_bound_transition_manifest
    default: block
    candidate: explicit read-only adoption manifest for proved equivalent entries only
    prerequisite: immutable source and destination binding, unique identity and complete comparison
    forbidden: approximate financial match, authorize deletion, clear uncertain intent
  history_evidence:
    future_owner: H5_evidence_verifier
    default: unverified
    prerequisite: bounded coverage, complete dispositions and separately reconciled units and totals
    forbidden: counts alone, empty ancient windows, manual completeness boolean override
```

The candidate NAV treatment is a recommendation to investigate, **not** an
accounting conclusion. A projection may be non-imported only after its financial
effect is proved represented elsewhere and retained in reconciliation. Without
that proof it still blocks the account, even when its value is zero. Principal,
valuation return and compensation must not become three copies of the same cash.

For same-currency executions, a zero FX field is not itself proof of unity.
Require source base currency equal to the independently verified quote currency,
an exact evidenced unit scale, signed totals and separately reconstructed fees.
Do not fill absent fields merely because an equation has a plausible solution.
Cross-currency rates still require source-backed direction and gross/base totals.

Transfers, positive tax adjustments and negative/reversed income may have no
faithful representation in the existing native activity model. A refusal is a
valid contract outcome. Require a separate representation decision and pinned
native readback/totals proof; do not force every source case into BUY/SELL or
nonnegative DIVIDEND/FEE/INTEREST fields.

## Proposed transition and history evidence

Use a private source-bound evidence manifest, separate from the write-intent
journal. Its document digest identifies the evidence document, **not** a new
broker event ID. The eventual schema must bind:

- Schema/policy revision, adapter and converter revision where actually known;
  source account, approved destination origin/account and bounded date scope.
- Hashes of individual raw responses, statement bytes, normalized source set,
  verified quote mapping and complete active destination snapshot.
- Each source stable identity, or projection's exact response provenance and
  occurrence, to an explicit disposition: proposed activity, exact existing
  activity, evidenced cash-only movement, evidenced projection, or unresolved.
- For adoption, exactly one source event and one existing created activity ID,
  complete immutable DTO/profile evidence and the independently justified date
  representation. No destination ID or source identity may be reused.
- Separate discrepancy records with compared fields, source evidence and a
  reviewed rule, never a generic tolerance or a success flag suppressing errors.

Minute truncation can be proposed only where the actual producer and source
timezone transformation are established. It does not explain arbitrary timestamp
differences. Existing recent trade fees and instants differ; those entries must
remain unresolved rather than adopted or rewritten. A repair candidate is a
different, separately approved deliverable, not a successful adoption result.
Unknown historical producer provenance remains explicitly unknown.

Reconciliation must preserve Decimal precision and multiset multiplicity, including
separate same-day payments. It must separately account for quantities, gross/net
payments, withholding, commission/AutoFX, funding/sweeps, fund principal and
valuation projections. Do not mix currencies or equate ledger cash flows with
portfolio performance. The observed one-cent trade/CSV delta needs a per-event
source-derived rounding explanation; it does not authorize a global one-cent
epsilon. Changed descriptions require an evidenced semantic mapping, not fuzzy
normalization. CSV footer/annotation dispositions must be explicit.

A candidate completeness verifier must reject any unresolved financial row,
relation, coverage gap, duplicate/conflicting stable identity or changed bound
input. Wide/split agreement is corroboration, not sufficient proof. Account
inception/older retention and opening positions need independent evidence; record
the tested bounds without claiming unlimited look-back. Positive and negative
fixtures must exercise each newly approved exception independently.

Only such a verifier could produce a scoped history evidence reference for a
future importer. The current `history_completeness_verified` flag remains false
for characterization archives; this specification supplies no override. A
write-free saved-input replay validates capture-time shapes only. Real preflight
must use fresh reads and independently validated current cash, never an old clock.

## Phases and validation gates

| Phase | Proposed deliverable families after scope approval | Required gate |
| --- | --- | --- |
| H1 Ledger policy | Separate fund-event and NAV-reconciliation contracts | Principal/valuation/compensation not double-counted; every unresolved financial effect blocks |
| H2 Dividend associations | Separate payment-link, untaxed-payment and signed-adjustment contracts | Missing/multiple/reversed/offset cases tested independently; no inferred association or zero tax |
| H3 Legacy executions | Separate field, quote-unit and transfer/action contracts | Reconstructed signed totals/fees/units; unsupported representations remain blocked |
| H4 CSV adoption | Read-only source-bound transition manifest | Exact ownership/equivalence and immutable input binding; mismatch or changed evidence refuses adoption |
| H5 Evidence verifier | Scoped complete-history evidence validator | Full disposition/coverage reconciliation, no boolean bypass or counts-only proof |

These are deliverable families, not one-hour implementation tickets. Split each
named contract into roughly one-hour characterization/implementation units only
after approval; link dependencies rather than adding a prose work queue. Each
contract owner owns its focused negative/positive regressions and any native
representation proof. H4 consumes proved H1-H3 contracts; H5 consumes all required
contracts and H4 dispositions. Independent contracts can be specified separately,
but implementation remains sequential. Acceptance owner `infra-8tt.56.11` alone
owns C13-C14 integrated totals, repeat-zero, recovery and real write-free preflight;
those criteria must not be duplicated in H1-H5 issues. Existing yield-policy
owner `infra-8tt.56.14` retains its adopted policy boundary; extending that policy
or relaxing unsupported-category handling requires Florent's separate explicit
approval. This specification does not reopen the already adopted EUR treatments.
Production owner `infra-8tt.56.12` alone owns C15.

## Native representation evidence and open decisions

The adopted yield policy records pinned Ghostfolio3.81.0 source at
`920d0787541a8568920fc11f978aa01e5a52c581` and isolated native evidence for the
bounded EUR yield convention. Its nonnegative quantity/price/fee DTO validation
does not prove a signed tax-refund or reversal model. Reuse the immutable core
unchanged; all new identities, source rules, manifest validation and accounting
decisions belong to broker-specific adapters or operator tooling.

Approve eventual contract scopes individually, including financial reporting
choices and unresolved evidence acquisition. Approval of this specification is
not approval to collect new broker sessions, run real mutation tests or create
implementation issues silently. No legal/tax characterization is inferred here.

## Rollback and blast radius

This change modifies this specification only; original captures and current
runtime behavior are unchanged. After publication, revert its exact scoped commit
with `git revert <specification-commit>`; do not delete private archives or reset
the worktree. Access to the repository and baseline Git blob was verified before
editing. Blast radius: documentation and proposed decision scope only.

Future approved implementations require atomic commits, offline synthetic
regressions and owned disposable labs. A source-bound adoption manifest must not
clear uncertain requests or bypass the existing account lock/journal. Production
candidate manifests, backup/restore access, exact-created-ID rollback, cron stop
and destructive authority remain C15 prerequisites. Restoring cash alone cannot
undo activities. No sibling edit, production interruption or financial rollback
is authorized by this proposal.
