# DEGIRO → Ghostfolio: source contract and gated delivery plan

## Scope and authorization boundary

This plan extends FINDINGS.md; it does not reopen the selected connector, TOTP
availability, CSV fallback or rejection of picsou as an activity source.
Florent approved Phase 0 on 2026-10-08 with Option C below. Phase 1 is authorized.
Florent authorized local Git and GitHub repository initialization on 2026-10-08.
Commits, pushes, live Ghostfolio writes and deployment still require Florent's explicit request; scope approval does not authorize them. Files are local drafts
until a commit is requested. Beads owns execution state and acceptance evidence.

Deliver one DEGIRO login/source account per instance into one existing Ghostfolio
account: executed BUY/SELL, paid DIVIDEND with linked withholding, separately
identified FEE, and verified current cash in the target account currency. Multiple
accounts use separate instances, with source and target included in dedup identity.
Stocks/ETFs are the initial instrument scope. Unsupported instruments, corporate
actions, shorts, interest, refunds and reversals require explicit diagnosis rather
than silent conversion. A relevant unsupported or ambiguous event blocks writes
for the target account. Known FX legs, deposits, withdrawals and sweeps are
classified/reconciled cash movements, not synthetic security trades.

No shared package, monorepo, IBKR repository modification, auto-auth/security-token
feature, automatic corporate actions, multi-login credential configuration or live
cleanup execution is included. CSV backfill remains an external tool with a tested
transition to API synchronization. Production rollout has its own approval gate.

## Inspected sources

Repositories were cloned once under the environment-managed scratch directory:
`/home/flow/tmp/degiro-source.drPp6G/`.

| Source | Inspected revision | Relevant full chain read |
| --- | --- | --- |
| [degiro-connector](https://github.com/Chavithra/degiro-connector/tree/22691b5e355094ba8b52c364bb3a5f33d9cc1bbc) | `22691b5e355094ba8b52c364bb3a5f33d9cc1bbc`, project version `3.0.36` | README trading/auth, portfolio, account and product-ID sections; trading API/lazy loader; session/connection/abstract action; credentials/login/account/transaction/product models; complete connect, client-details, account-info, transactions/orders history, overview/report, products-info, update, upcoming-payments and logout actions; associated examples |
| Local IBKR sibling | `2d2589908a03fa0ceec65487759bdb0f1a272475` | Complete `ibkr_to_ghostfolio.py`, requirements, Dockerfile, entrypoint, conventions; cleanup identity boundaries inventoried |
| [Export-To-Ghostfolio](https://github.com/dickwolff/Export-To-Ghostfolio/tree/9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5) | `9e35bd602f054f563b8c728bcb36dc5eb2bbcaa5` | Complete `degiroConverterV3.ts`, activity model, relevant test cases |
| Local KB | `bundle/operations/ghostfolio/index.md` → `api-traps.md` | Applicable, stable, verified 2026-10-07; current-profile/accepted-import requirements also checked in sibling source |

The connector source version must be matched to the installed PyPI distribution
before dependency pinning; the project version string alone does not prove equality.
README examples are partially stale: the transactions example uses an obsolete
request class/signature, while action source and executable examples agree.

## Source contract: confirmed facts and limits

### Account movements do not provide an authoritative event taxonomy

`trading/models/account.py` defines:

```
OverviewRequest(from_date=<date>, to_date=<date>)
AccountOverview(cash_movements=[CashMovements(...)])
CashMovements: balance, change, currency, date, description, id,
               product_id, type, value_date
```

All movement fields are optional. `type` is an unrestricted string, not an enum.
Neither action, model nor README defines dividend/fee/tax/FX values or a mapping.
The README lists additional fields (`orderId`, `unsettledCash`, `total`) which the
cash model does not preserve by default. Use `raw=True` and validate the raw envelope
and relevant fields ourselves; missing relation fields are not assumed to exist.

Exact call:

```
get_account_overview(overview_request=OverviewRequest(...), raw=True)
```

It performs one GET to `/portfolio-reports/secure/v6/accountoverview` with
`fromDate`, `toDate` serialized as `DD/MM/YYYY`, plus `intAccount` and `sessionId`.
It returns the raw envelope or `None` after logging exceptions. `None` must become
an explicit adapter failure, never an empty account.

**Conclusion:** the feed has candidate classification and relationship fields;
source inspection cannot confirm a complete semantic distinction. C3 is a required
read-only characterization gate. Exact observed types/descriptions become keyed
YAML rules. Do not use a generic "everything else is a dividend" rule.

V3's CSV converter corroborates localized description matching for transaction
costs, withholding and standalone platform fees, plus ignored FX/deposit/sweep
rows. Its pairing heuristics and residual-to-dividend behavior are not transferred
into the API adapter. CSV behavior does not establish API `type` values.

### Transaction dates and pagination

Exact current call:

```
get_transactions_history(
    transaction_request=HistoryRequest(
        from_date=<date>, to_date=<date>,
        group_transactions_by_order=False),
    raw=True)
```

It performs one GET to `/portfolio-reports/secure/v4/transactions`; dates use
`DD/MM/YYYY`. The request contains no limit, offset, cursor or page parameter.
The response model has only `data: list[HistoryItem]`; the action implements no
pagination. There is no documented maximum look-back, range size, truncation
signal or inclusive/exclusive boundary guarantee in the inspected subsystem.
Example ranges exceed a year, but they are not evidence of server completeness.

Use configurable bounded date chunks with overlapping boundaries and stable-ID
dedup. Reject conflicting repeated IDs. C4 compares ID sets for a wide interval
and its split intervals against an independent statement, including actual
boundary executions and an older interval. Neither count agreement nor an empty
old interval alone proves unlimited history. Publish only observed bounds; initial
backfill uses CSV where API completeness is not established. Window/chunk defaults
are selected from C4 evidence rather than an assumed 365-day broker limit.

### Product, commission, FX and cash semantics

Transactions carry `productId`, `buysell`, date, price, quantity, totals, base-currency
fees, AutoFX fees and multiple FX rate fields. They do not directly carry the full
instrument metadata. `get_products_info(product_list=[...], raw=True)` resolves
product ID to ISIN, symbol, instrument currency/type and exchange. `quantity` is
typed as integer in the library model; raw validation preserves fractional values.

`get_client_details()` exposes `data.intAccount`; set the account on Credentials
after discovery without logging the client response. `get_account_info()` exposes
base currency and account cash information. Current `get_update()` accepts
`UpdateRequest(option=UpdateOption.TOTAL_PORTFOLIO/CASH_FUNDS, last_updated=0)`.
README describes `degiroCash`, `flatexCash`, `totalCash`, but nested shape, units,
freshness and settlement interpretation need C6. A historical `balance` on the last
overview row is not used as a current snapshot.

C5 proves fee signs, which total includes which commission/AutoFX cost and FX rate
direction with actual same/foreign-currency executions. Ghostfolio activity price
and fee share one currency: base fees require evidenced conversion into instrument
currency. A cost already in an execution must not become a second standalone FEE.
C6 requires source/target currency equality; mismatches stop balance updates.

### Library logging and HTTP failure boundary

`ActionConnect` logs the complete successful login model at INFO, including
`sessionId`. Other actions log exception text and sometimes raw HTTP bodies;
session IDs also appear in query strings/paths. `session.send()` has no explicit
timeout. The login maintenance helper additionally uses module-level
`requests.get()` without a timeout.

Passing a logger to `TradingAPI` is insufficient: `setup_one_action()` does not
forward it to action constructors. Use the inspected action class methods with an
explicit isolated logger that emits no raw records, a shared bounded requests
session and explicit session ID/credentials. Maintain connection/discovery/logout
in functional application helpers. A function wrapper on the session send path
enforces connect/read timeout without a custom application class. The maintenance
helper's module-level call also needs scoped bounding; prove this in C2 before
real login. Authentication retries are bounded and cannot repeatedly hammer TOTP
login after captcha, in-app approval or credential failure.

Suppress connector/urllib3 raw logs, normalize boundary exceptions to controlled
messages and remove unsafe exception chains. C1 tests all credential/session/OTP
sentinels at DEBUG on success, HTTP error, validation error and unexpected failure.
No live secrets are used in tests. Construct Credentials directly from `os.environ`;
do not use the library JSON-file/DEGIRO_ACCOUNT credential loader.

## Reuse decision

**Option C: deliberate copy with provenance and anti-drift enforcement.** Pin
the explicitly reviewed release SHA in CORE_PROVENANCE.md. The original frozen
base was replaced with v2.2.0 on Florent's request (2026-10-08). The sibling remains
read-only. There is no package, monorepo or sibling refactor.

- `ghostfolio_core.py`: importable broker-agnostic functions copied byte-for-byte.
- `degiro_to_ghostfolio.py`: imports the core; owns fetch, broker conversion and
  identity, existing-activity indexes, holdings/manual matching, URL policy,
  balance freshness/currency guards and orchestration.
- `CORE_PROVENANCE.md`: authoritative keyed YAML block recording repository,
  exact source commit/path/blob SHA256 and selected functions/imports/constants.
- `scripts/check_core.py`: deterministic projection/verification, with explicit
  `--write` for human-controlled propagation only.

The canonical source is still a mono-file. Whole-file equality with it is
impossible, so the maintained artifact is its deterministic projection. AST
locates allowlisted top-level units; the checker slices their original bytes,
including function signatures, bodies, comments and line endings. It never uses
AST unparsing or reformats code. Units retain source order with a fixed LF
separator. CI reconstructs the expected module from the canonical pinned Git
commit and fails on any byte difference, including whitespace, imports/constants
or module structure. CORE_PROVENANCE.md lists every selected function and its
dependency units. Broker-dependent helpers never enter the projection.

Choose this stronger check over SHA-only monitoring: a source pin cannot detect a
local edit. Additionally compare upstream main HEAD to the pin on PR, push,
manual dispatch and weekly CI. A mismatch emits a warning and job summary for
human propagation, even when core bodies are unchanged. It does not auto-sync,
bump the pin, publish images or write external issues/comments. Failure to read
the canonical source or upstream HEAD fails the check rather than reporting success.
Local checks use `git show <pin>:<path>`, never the sibling working tree; CI uses
an isolated source checkout. Offline mutation tests exercise both guard outcomes.

Propagation: review newer IBKR selected functions and dependencies, update the
full pin and blob hash in CORE_PROVENANCE.md, explicitly regenerate, inspect the
semantic/byte diff and run offline regressions plus integrity check. Commit/PR
still requires authorization. Missing/renamed units fail until the manifest is
deliberately reviewed. Never adapt the guarded file for DEGIRO; broker changes
stay in the adapter. Restore pin and generated artifact together for rollback.
Exact propagation commands live in CORE_PROVENANCE.md.

If IBKR later adopts the same `ghostfolio_core.py`, the two projects can converge
on a whole-file hash comparison. This is a future path, not current work. Keep
functional Python without classes/type hints. The core uses requests and the
standard library; the adapter/checker use PyYAML. The broker connector is added
in its later phase. Port only the existing regressions belonging to this boundary.

The historical handoff incorrectly listed `validate_ghost_host` and
`ghost_exchange_access_token` for the original pin. They exist in v2.2.0, but
automatic token exchange remains outside the current DEGIRO scope. Add the
approved target URL policy before any token-bearing request. Identity-sensitive helpers are adapted rather than copied blindly:
`IBKR#` trade comments, dividend date keys, cleanup matching and broker-shaped
inputs. Preserve inactive/redacted context rejection and buy-before-sell accepted
evidence from the newer core. Only recognized HTTP 400 symbol-resolution failures
permit drop/retry; an uncertain POST blocks subsequent account writes, including
cash. A failed/degraded sync exits non-zero.

Trade identities include DEGIRO source account and execution ID, with target account
included in lookup keys. Cash identity is based on stable observed row/payment IDs,
not just ISIN plus calendar day. C3 proves whether tax linkage is unambiguous. Keep
separate same-day payments; do not sum different currencies or infer a tax association
from date proximity alone. An existing canonical identity is never suppressed just
because another canonical dividend occurs nearby. Manual/CSV duplicate reconciliation
requires financial evidence and one-to-one matching; ambiguity stops the account.

Minor-unit conversion logic is reusable, but DEGIRO input units are characterized
before enabling a market rule. No inference from an IBKR-only production check.

## Phases and numbered validation gates

Execution is sequential, one implementation issue in progress at a time. Atomic
units are approximately one hour, including focused offline tests. Gates may
expose additional work; that work stays in the owning issue if in scope. No phase
claims later operational acceptance as implementation evidence.

| Phase | Gate | Evidence required before proceeding |
| --- | --- | --- |
| 0 — scope | Approval | Florent approves this scope and gated approach; no code yet |
| 1 — scaffold | Provenance + anti-drift | Exact pinned byte projection, CORE_PROVENANCE.md function list, failing integrity CI/main-advance signal, propagation procedure, license/AGENTS.md and offline regressions; Git init/first commit only when requested |
| 2 — safe read adapter | C1 | Env-only credentials; captured DEBUG/error logs contain no credential, OTP or session sentinel |
| 2 | C2 | Offline mocked auth/discovery/history/product/report/update/logout failures, `None`, malformed envelopes, timeout and maintenance handling; bounded network calls and overlap-ID conflict rejection |
| 3 — read-only characterization | C3 | Actual locale/types/descriptions/relationship IDs for dividend, tax, autonomous fee and FX; anonymized synthetic equivalent fixtures; unsupported categories explicitly gated |
| 3 | C4 | Wide vs split-window transaction ID sets, statement totals/IDs and boundary behavior; oldest tested dates recorded, no claim of unlimited look-back |
| 3 | C5 | Same/foreign-currency trades prove price currency, fee signs/totals/AutoFX and FX direction; product/quantity/minor-unit behavior |
| 3 | C6 | Current cash shape and timing, flatex/DEGIRO non-duplication, source base/target currency equality against account statement/UI |
| 4 — trade conversion | C7 | Offline trade normalization, strict B/S, stable account-scoped execution identities, fractional quantities, fee conversion and holdings regressions |
| 4 — dividend conversion | C8 | Offline payment/withholding linkage, same-day distinct payments, unknowns, mixed currency, correction/refund/reversal diagnostics; no upcoming payment import |
| 4 — standalone fee | C9 | Installed-version Ghostfolio source confirms FEE/MANUAL contract; transaction-cost exclusion and returned evidence tested, then isolated server acceptance |
| 4 — balance | C10 | Current valid matching-currency cash only; zero/missing distinction, freshness; no PUT on uncertain or ambiguous account state |
| 5 — orchestration | C11 | Mocked end-to-end pytest: duplicate/conflicting IDs, mapping changes, manual/CSV match ambiguity, inactive/redacted context, partial/uncertain outcomes, accepted buys before sells, DRY_RUN blocks every Ghostfolio mutation |
| 5 — runtime | C12 | Full pinned dependency closure, source/package parity, offline pytest, dependency audit, amd64/arm64 non-root builds and cron/run-once smoke; CI publishing disabled until authorized |
| 6 — acceptance | C13 | Disposable Ghostfolio seeded synthetic scenario: exact activities and totals/cash, second run zero imports, unresolved-symbol/uncertain-result recovery |
| 6 | C14 | CSV V3 overlap transition and broker-scoped cleanup/recovery preflight offline/isolated; real read-only DRY_RUN reconciles statement, sends zero Ghostfolio writes |
| 7 — optional production | C15 | Separate explicit bounded-write/deployment approval; exact candidate manifest, target backup, tested restore access, first live and repeated scheduled run reconciliation |

Live characterization is a distinct read-only operator procedure, not pytest or a
production canary. Broker login/logout changes the authentication session only;
no order-placement action is used. Private input stays off-git. Never emit raw
client-details, auth headers or HTTP bodies into logs. Exact secret-store path and
runtime access remain operational prerequisites; no secret values belong here.

## Artifacts and validation ownership

Implementation produces the DEGIRO adapter and immutable copied core, provenance,
anti-drift checker/CI, adapted offline tests, full pinned
runtime/dev manifests, mapping/config examples, non-root Docker + supercronic
harness, CI checks, README/runbook and broker-scoped cleanup utilities as needed
for C14. Cleanup retains its utility boundary; broker matching changes stay outside
the guarded core. Configuration defaults to `DRY_RUN=1`; explicit live mode is
documented only after acceptance. YAML rules hold repeated classification data;
they do not duplicate authoritative source balances or transaction records.

Core implementation children own their focused tests. The acceptance child owns
isolated end-to-end evidence and real DRY_RUN reconciliation. The rollout decision
owns live import and scheduled-run evidence, and remains open if not authorized.
Actual deployment belongs to an infra handoff after approval.

Before each authorized commit: `.venv/bin/python -m pytest -q`, syntax/security
checks appropriate to touched logic, semantic diff, `git diff --numstat` and
`git diff --check`. New external HTTP/credentials handling receives a security
review before merge. The exact available review workflow is resolved in scaffold
work; independent delegation occurs only if explicitly requested or required by
an applicable review skill. Never test against the live shared Beads database or
live financial state. No secrets are put into Beads or KB.

## Rollback and blast radius

Planning touches this local repository and project-routed Beads records only.
No Git repository existed at planning start. New draft plan removal is recoverable
by moving it into a scratch backup; existing handoff files remain untouched.
Beads corrections use `bd update`/dependency edits, not deletion of shared records.

Before commits, local implementation edits restore from verified pre-edit backups;
after explicitly authorized commits use `git revert <exact-change-commit>` in this
repository. Do not use reset or touch the sibling. Disposable acceptance state is
restored/reset only inside its isolated instance and must never share production
database volumes, endpoints or broker credentials used for offline tests.

Production rollback is deliberately not asserted today: deployment image, target
account snapshot and restore credentials have not been inspected. C15 must record
the exact image digest, cron-stop mechanism, backup identifier, restore command and
tested access before any write. Restoring cash alone does not undo imported
activities. Bounded exact-created-ID deletion or database restoration needs the
operator's explicit destructive authorization. No generic cleanup is a rollback.

## Research verdict

The main unknown is now bounded: the connector offers raw event data but no
documented semantic taxonomy, history-completeness guarantee or commission FX
definition. Those facts remain numbered read-only gates, not implementation
assumptions. The KB lookup was applicable and sufficient for Ghostfolio-specific
traps; new connector facts remain canonical source-backed project research.

## Approved release refresh (2026-10-08)

Florent requested initialization using the current IBKR setup before continuing
implementation. The reviewed v2.2.0 source is pinned in CORE_PROVENANCE.md. The
previous selected core function bodies are unchanged. Auto-authentication and
Apprise are new upstream features, but are outside the current DEGIRO broker
contract; adopting them is a separate scoped decision. Reuse remains Option C.
The sibling is read-only. GitHub settings and applicable security/release workflows
are mirrored; container build gates are enabled with Phase 5 packaging rather than
requiring checks for artifacts that do not yet exist. C1-C15 remain unchanged.
