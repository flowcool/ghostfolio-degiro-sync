# Standalone fee contract and isolated acceptance

## Target-version evidence

The read-only production version probe on 2026-10-08 returned Ghostfolio `3.81.0`:

```sh
ssh ugreen docker exec ghost grep -m1 version /ghostfolio/apps/api/package.json
```

This is dated evidence, not a pin on production. The source was inspected in an
existing scratch checkout at tag `3.81.0`, commit
`920d0787541a8568920fc11f978aa01e5a52c581`:

- [CreateOrderDto](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/libs/common/src/lib/dtos/create-order.dto.ts)
  accepts FEE, non-negative fee/quantity/unitPrice, currency and ISO timestamp.
- [Import validation](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/apps/api/src/app/import/import.service.ts)
  requires a UUID or `GF_` symbol for explicit MANUAL imports. A free-text
  description from the CSV converter is not a valid explicit MANUAL symbol.
- [Activity creation](https://github.com/ghostfolio/ghostfolio/blob/920d0787541a8568920fc11f978aa01e5a52c581/apps/api/src/app/activities/activities.service.ts)
  forces non-investment activities to MANUAL and preserves valid custom symbols;
  otherwise it generates a UUID. Import sets `updateAccountBalance: false`.

## Adapter policy

Only observed annual exchange-connection debits become standalone fees. Rules
remain canonical in `cash-rules.yaml`. The row must have no product or order
relation, EUR currency equal to the observed EUR base currency, a negative change,
and an exact cent amount representable as a JSON number. Positive refunds, zero
amounts, unknown fee categories, mixed currencies or unverified units block.
The whole ledger is classified first; unsupported categories still block writes.

Synthetic example:

```json
{
  "accountId": "target-a",
  "comment": "DEGIRO#123:FEE:104",
  "currency": "EUR",
  "dataSource": "MANUAL",
  "date": "2025-12-31T23:00:00+00:00",
  "fee": 2.5,
  "quantity": 1,
  "symbol": "GF_DEGIRO_123_EXCHANGE_CONNECTION_EUR",
  "type": "FEE",
  "unitPrice": 0
}
```

Each row keeps its own comment, even when multiple charges share a symbol/date.
The source account scopes the symbol; target account participates in adapter
lookup. Native duplicate detection does not compare accountId: a routing change
cannot rely on native dedup alone. Account-switch reconciliation belongs to the
orchestration gate. Description text is not an identity.

Brokerage ledger rows require exactly one execution with equal product and UTC
instant, matching base currency and exact brokerage debit. An available execution
order reference must also agree. Two ledger commissions cannot evidence the same
execution. Total fees must equal non-positive brokerage plus AutoFX fees. Only
the trade activity carries that total; neither commission nor cash-only FX legs
become a second FEE. Missing or ambiguous execution evidence blocks.

## Disposable server acceptance

On 2026-10-08, agentvm ran `ghostfolio/ghostfolio:3.81.0` at image digest
`sha256:7c925671dba267cc2175195f064b42b9733f3ea170a21db488b7d2be3319e088`,
with separate Postgres/Redis on an internal Docker network. There were no host
binds, production credentials, production database connections or persistent
database volumes; Postgres data used tmpfs. The test driver asserted the lab
Compose project, exact image and internal network before sending a request.

The probe used the synthetic fixture from `tests/fixtures/degiro_contract.yaml`,
one newly created lab user/account, and the actual immutable core evidence matcher:

| Probe | Observed result |
| --- | --- |
| Local core DRY_RUN before writes | Proposed one fee; server activity count remained zero |
| POST import with `dryRun=true` | Exact preview accepted by core; stored activity count zero |
| POST activities-only import | One FEE/MANUAL; fee 2.50 EUR, quantity 1, unitPrice 0 |
| Core reconciliation and complete GET activities | Exact target/comment/UTC instant/currency/financial fields and stable custom symbol |
| Repeat identical import | Empty accepted list, stored count remained one |
| Preview with free-text MANUAL symbol | HTTP400; stored count remained one |

The temporary driver command was `.venv/bin/python tmp/fee-lab/acceptance.py`;
its success summary and provenance are recorded in `infra-8tt.56.7`. Temporary
lab/auth material stays ignored. To reproduce, create a fresh isolated project at
the pinned image with empty Postgres/Redis, create a disposable user and account,
normalize the synthetic fee fixture, and run the probes above in order. Never
point this mutating procedure at production. Stop/remove only that disposable
Compose project afterward; no production delete is part of rollback.

Offline regressions live in `tests/test_degiro_fees.py`. Core returned-evidence
checks reject changed amounts/date/account/comment/type/currency/data source,
missing created IDs and error rows. Empty acceptance is evidence of zero created
rows, not proof that all proposed fees exist in the intended account. This gate
does not establish end-to-end orchestration, history completeness or live rollout.
