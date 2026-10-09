# Proposed historical contract extension

This is a proposal for review, not an approved implementation scope or an active
work queue. The approved delivery plan and C1-C15 remain unchanged. Beads owns
execution; existing policy owner `infra-8tt.56.14` still requires Florent's approval
before relaxing unsupported-category handling. Acceptance owner `.56.11` remains
open. Production financial writes, cleanup and deployment remain unauthorized.

## Problem and decision

The fresh broad history makes the recent contract insufficient for a complete
backfill. The [source contract](../source-contract.md) records exact observed
scope: window-dependent id0 NAV rows, legacy fund movements, zero interest and
compensation, unmatched/reversed withholding, CAD quote units, transfers, legacy
FX/financial shapes and old CSV timestamp truncation. Dropping any of these to
make preflight green is not a valid extension.

Recommended approach: approve a bounded characterization/design phase, retain all
write blocks, and review the resulting category/identity policies before coding
extensions. A supported-history start date alone does not erase older destination
holdings or prove opening balances; no automatic cutover is proposed.

## Phases and validation gates

| Phase | Roughly one-hour atomic deliverables after scope approval | Required gate |
| --- | --- | --- |
| H1 Ledger policy | Characterize original fund transaction/NAV/compensation relations; separately define zero/positive/reversed interest representation | Every relevant row accounted for explicitly, stable identities distinguished from projections, no silently discarded amount; approve accounting policy before adapters change |
| H2 Dividend associations | Prove payment/withholding linkage using retained statement and unique source groups; separately characterize untaxed HKD payments and positive tax adjustments | No proximity-only pairing, candidate summation or inferred zero tax; ambiguity stays blocking; currency/quote units independently proved |
| H3 Legacy executions | Characterize same-currency zero FX and absent financial fields; separately establish CAD units and transfer/corporate-action boundaries | Signed totals/fees/FX independently reconstruct, no invented zero/rate or quote scaling; transfers stay blocked absent an explicit supported event model |
| H4 CSV adoption | Define source-bound explicit adoption manifest for exact existing entries, including minute truncation; validate mismatches and omitted events separately | Unique account-scoped ownership, full immutable DTO/source evidence and reviewed identity policy; manifest cannot clear uncertain requests or authorize deletion |
| H5 Acceptance | Add synthetic regressions per approved rule and isolated native import/readback; perform complete private statement reconciliation and write-free real preflight | C13-C14 exact quantities/fees/cash, repeat zero, all relevant history represented, zero production writes; no history flag override from counts or empty ancient windows |

Create the atomic implementation issues only after agreeing their scope. Keep one
implementation issue in progress and one owner per acceptance criterion. Existing
policy owner `infra-8tt.56.14` retains interest/compensation; new independently actionable scopes
must not be hidden inside that issue or close acceptance prematurely.

## Native representation evidence and open decisions

The inspected native Ghostfolio3.81.0 source at
`920d0787541a8568920fc11f978aa01e5a52c581` has an `INTEREST` activity enum
(`prisma/schema.prisma`), nonnegative quantity/price/fee DTO validation
(`libs/common/src/lib/dtos/create-order.dto.ts`) and separate interest accumulation
(`apps/api/src/app/portfolio/calculator/portfolio-calculator.ts`). This is a
candidate native contract to test, not proof that broker compensation is interest
or that the immutable shared core accepts a new broker activity unchanged.

The observed Flatex interest is zero; positive interest behavior is not
characterized by those broker rows. Monetary-fund compensation and NAV economics
need a deliberate representation choice. Cash-only handling is an explicit policy
option to review, not a silent category bypass. Dividend tax refunds/reversals
also need a financial representation, not negated fees forbidden by the DTO.

## Rollback and blast radius

Characterization changes private evidence and aggregate documentation only.
Approved implementation would use separate atomic commits, offline fixtures and
owned disposable labs. Revert exact scoped commits to restore the previous strict
contract; retain source archives and unresolved journals. No sibling core edit,
production interruption or financial rollback is part of this proposal.
