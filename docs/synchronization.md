# Account synchronization and write gates

## Operator configuration

Set `GHOST_HOST` to an exact approved origin: `https://ghost.mylittlemess.fr`,
`http://ghostfolio:3333`, `http://localhost:3333` or `http://127.0.0.1:3333`.
The HTTP origins are for the existing private container network or isolated local
acceptance, not public credential transport. No arbitrary origin, URL credentials,
query, path prefix or redirect is accepted. Changing this policy requires review.

`GHOST_TOKEN` comes only from the environment. It is an already valid bearer;
Security Token exchange remains outside this scope. Use the off-git secret
pointer, never a command-line secret or committed environment file.

Required non-secret environment values:

| Variable | Meaning |
| --- | --- |
| `DEGIRO_ACCOUNT_ID` | Expected positive broker source identity discovered in the private read |
| `GHOST_ACCOUNT_ID` | Exact existing destination account identity |
| `MAPPING_FILE` | Explicit mapping file; default `mapping.yaml` |
| `DRY_RUN` | Defaults to `1`; strict boolean strings, invalid values fail |

Copy `mapping.yaml.example` to ignored `mapping.yaml`. Each ISIN maps to a Yahoo
symbol and independently verified quote currency. Broker tickers/currencies are
not verification and supply no fallback. Only currently characterized major
currencies and STOCK metadata pass the conversion guards.

Run through the SOPS environment loader described in [read-only.md](read-only.md):

```sh
DRY_RUN=1 .venv/bin/python degiro_to_ghostfolio.py --sync \
  --from-date 2025-10-08 --to-date 2026-10-08
```

The dated broker read still reports history completeness as unverified. A safe
DRY_RUN may propose activities but exits non-zero with that diagnostic. The real
account additionally contains deliberately unsupported interest/compensation,
which blocks proposals before any financial write. Setting `DRY_RUN=0` does not
override these gates: unverified history blocks live writes. CSV transition,
isolated end-to-end acceptance and explicit production authorization remain
separate requirements. No operator completeness override exists in this command.

The account/source IDs and mappings above are operator configuration, not secrets.
Do not print private snapshots to derive them. Read-only characterization remains
separate (`--read-only`, with required `--output`); its report/order options cannot
be combined with `--sync`.

## Whole-account preflight

One GET retrieves all Ghostfolio activities without offset pagination. Reported
count must exactly equal the list length; rows need unique created IDs,
unredacted finite financial fields and valid profile/date context. The complete
all-account list retains canonical ownership checks. Relevant target activities
must be active and current; unverified target types/holding data sources stop.
The destination account itself must be active, unredacted and in the broker's
characterized base currency.

Normalize the entire broker ledger, trades, paid dividends and standalone fees
before any mutation. Validate fresh current cash before import too; never leave
an account partly imported because a known balance ambiguity was deferred.
Canonical row comments compare exact financial evidence. Duplicate/conflicting
identities, changed mappings or ownership in another target stop. Nearby manual
or CSV candidates require explicit reconciliation, never automatic adoption.
Distinct canonical same-day payments remain separate.

Holdings derive from complete active target BUY/SELL context. Pending trades
must not make holdings negative. This conservative baseline is not an inferred
historical opening position: CSV/manual overlap and late historical insertion
need explicit diagnosis.

## Accepted outcomes and cash

Import the non-SELL batch first. Only the core's exact accepted evidence updates
holding arithmetic. The SELL batch is checked again against those actually
accepted buys. A lost response, degraded symbol retry, short acceptance,
changed returned fields or callback failure fences the account and blocks later
sells/cash. Only recognized symbol-resolution HTTP400 errors permit the copied
core to drop that symbol and retry; other HTTP400 errors fail immediately.

The adapter deliberately treats short acceptance as requiring reconciliation,
even though native import may return HTTP201 with no created rows. See the KB
account-ownership trap and [fee-contract.md](fee-contract.md). Run-scoped
uncertainty is recorded in the config and is never cleared within a run. A
durable lost-response/restart recovery procedure belongs to the isolated recovery
acceptance gate; this implementation does not claim it is production-proven.

After clean complete acceptance, the guarded cash callback checks freshness
again and calls the immutable writer. The bounded transport verifies the writer's
fresh GET account identity/currency/unredacted balance before allowing its PUT.
The API has no transactional compare-and-swap between that GET and PUT; operator
concurrency must be controlled in a separately authorized rollout.

## Transport and review boundary

The adapter temporarily binds `core.requests` to one bounded Session for a
sequential single-threaded run, then restores it even on failure. The immutable
file is never modified. Only GET account/list/activities, POST activities-only
import and PUT the exact target account are allowed. DELETE is always refused;
DRY_RUN permits only GET. Session proxy inheritance is disabled, timeouts are
bounded, TLS verification is enabled and redirects are refused. No transport
retry is configured; the core's bounded recognized-symbol retry is separate.

Core raw HTTP diagnostics are muted for the binding because their error paths
can include response bodies/exception URLs. The CLI reports fixed failure text
and counts only, without credentials or private payload dumps.

Offline tests in `test_degiro_sync.py` exercise the pure account orchestration
and real core calls with mocked Session.send. The production command does not
fabricate history proof or financial-write permission. Revert the scoped
orchestration commits to roll back; no production compensation is required for
implementation/testing. Disposable acceptance owns its own teardown procedure.
