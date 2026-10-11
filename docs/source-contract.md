# Observed DEGIRO contract

This documents the supported adapter contract, backed by pinned connector source
and synthetic regressions. The private API can change without notice.
`cash-rules.yaml` owns classifications; unexpected or ambiguous data blocks writes.

## Authentication and raw data

Each execution obtains broker username/password/TOTP from the configured vault.
The bounded broker session retains canonical connector headers and approved exact
origins, refuses redirects and exposes fixed diagnostics instead of raw responses.

The raw `cashMovements` fields observed include `id`, `type`, `description`,
`currency`, `change`, `date`, `valueDate`, `balance`, optional `productId`,
`orderId` and `exchangeRate`. Modeled cash responses would omit the extra fields.
Cash IDs are stable across wide/split reads. The `balance` field changes with
the requested date window; ignore only that field for overlap equality and never
use it as the current balance. All financial event fields must still agree.

## History and statement comparison

Window overlap compares stable IDs and exact financial fields, excluding only
derived cash `balance`. Cash statements use local offset timestamps and minute
precision, and UTF-8 decoding is validated. Order history is diagnostic and cannot
establish execution completeness. Cash-sweep annotations without amounts remain
distinct from cash-only signed sweep transfers. Private account history is not
community compatibility evidence or a proof of global broker retention limits.

The prospective checks permit a difference of at most0.01 only for uniquely associated
STOCK execution cash in a supported cent-valued currency, with contract size1.
Declared execution total, API cash and CSV amounts must remain within0.01 of each
other and of signed unrounded quantity times price; API/CSV amounts must be
cent-valued, while the declared execution total may retain subcent precision.
All identities, dates, descriptions, currencies, references and row multiplicities
remain exact. Other categories and ambiguous associations retain strict refusal;
this approval does not authorize arbitrary financial discrepancies.

See [history reach and request limits](degiro-history-limits.md) for the
distinction between observed historical access, unpublished broker limits and
repository policies.

## Extended historical read-only characterization

The exact cash-overview `data: {}` envelope is accepted as an empty collection;
other missing/malformed shapes fail. Empty historical windows do not establish
account inception or unlimited retention. Legacy `CASH_FUND_NAV_CHANGE` records
may share ID0 and differ across windows; the overlap guard refuses distinct rows
with the same identity. Never invent IDs, ignore financial changes or apply the
execution-cent tolerance to unstable fund records. Full-history completeness and
basis remain unverified until independently proved for the actual account.

## Cash taxonomy and dividend association

Observed types: `CASH_TRANSACTION`, `FLATEX_CASH_SWEEP`, `TRANSACTION`,
`COMPENSATION_BOOKING`. `CASH_TRANSACTION` contains paid dividends, withholding,
brokerage, FX, funding, annual exchange fees and interest. Its type alone is
insufficient. The observed exact French labels and restricted patterns live in
`cash-rules.yaml`; language changes need deliberate rules review.

Ten paid dividend rows and ten withholding rows form unique one-to-one groups on
product ID, currency and exact `date` and `valueDate`. Dividend changes are positive
and tax changes negative. There is no explicit shared payment-reference field;
matching requires exact grouping, a unique association and statement evidence.
Multiple same-product/date candidates remain separate and block ambiguous pairing.
Payment identity is the stable dividend row ID, never a calendar-day key. Upcoming
payments are excluded. No date-proximity matching or unconditional summation is safe.

Under the [adopted cash-yield convention](interest-compensation-policy.md),
characterized zero EUR Flatex interest is retained as zero INTEREST and positive
EUR monetary-fund compensation as separately identified INTEREST. Exact type,
description, cent-valued amount, offset dates and stable ID are required. Unobserved
nonzero interest, zero/negative compensation, unknown fields/relationships or other
currencies block account writes; no gross income or tax is inferred.
Known cash-only FX/funding/sweep rows are not security trades or fee activities.

## Execution, commission and FX

Observed SELL executions have negative quantities; Ghostfolio uses absolute
quantity plus explicit BUY/SELL type. Prices and fractional quantities come from
raw execution data. Product metadata supplies ISIN, security currency and product
type; broker tickers do not establish Yahoo identities.

For the three observed cross-currency executions, `fxRate` and `grossFxRate`
reconstruct base total from security-currency total to one base-currency cent.
`nettFxRate` does not; never use it to apply fees a second time. Base currency is
EUR. All brokerage and AutoFX fees are negative and
`totalFeesInBaseCurrency = feeInBaseCurrency + autoFxFeeInBaseCurrency`.
Each brokerage cash row has a unique matching execution on exact timestamp and
product; its EUR change equals that execution's `feeInBaseCurrency` exactly.
These cash rows must not become separate FEE activities in addition to execution
fees. Unknown signs/rates, refunds, multiple candidate matches or unsupported units
remain fail-closed. Unobserved BUY/unit cases need validation in their owning gate.

Standalone annual exchange fees follow the separately verified
[FEE/MANUAL contract](fee-contract.md). Brokerage and AutoFX are excluded from
those fees; ambiguous commission-to-execution reconciliation blocks the account.

## Import format diagnostics

The operator distinguishes the supported financial contract from recognized legacy
fund markers and unknown/incompatible response shapes. No broker-provided format
version or calendar cutoff has been proved: a compatible 2019 payload uses the
same checks as one dated 2026. `CASH_FUND_NAV_CHANGE` and `CASH_FUND_TRANSACTION`
produce a legacy monetary-fund format error; missing/nonfinite execution fields
and nonpositive FX rates produce separate incompatible-contract errors. A zero
rate is not automatically evidence that an API response is old.

Errors are fixed strings, preserved through the sanitized broker reader and both
CLI modes. Only the exact cash-overview `data: {}` envelope is an empty cash
collection; other unknown envelopes are never converted to empty history. Known legacy detection stops before merging cash events or any
financial dispatch; preflight still validates the entire account afterward for
compatible shapes. No missing amount, identity, currency or rate is synthesized.
Read-only diagnostics still guarantee logout and retain credential privacy.
Future historical support is separately tracked; these messages do not broaden
import support or authorize a cash/category exception.

## Current cash

`account_info.data.baseCurrency` isEUR. `update` returns three named wrappers:
`portfolio`, `totalPortfolio`, `cashFunds`, each with a `value` list. The named
`totalPortfolio` values include `totalCash`, `degiroCash`, `flatexCash` and
`pendingSettlement`. Observed `totalCash = degiroCash + flatexCash`; `degiroCash`
must be zero under the supported EUR cash contract. The EUR cash-fund value and `FLATEX_EUR` pseudo-position
size both equal `totalCash`: these are cross-checks, not extra amounts to sum.
Adding them would double-count cash. Other currencies are not converted silently.
`cryptoTotalCash` also equals `totalCash` in the observed response and is an
optional cross-check, not a new balance to add. Cash pseudo-positions include
optional `accruedInterest` fields with no `value` key; required cash amount
fields must still be present and numeric.

The adapter records UTC fetch start/end timestamps separately from source
`lastUpdated` values, whose units are not assumed. Only a fresh live snapshot with
consistent wrappers and target currency equal to the broker base currency can
drive a cash update. Historical overview balances cannot. Freshness, missing
fields, conflicting duplicate names and account-currency mismatch remain guards.

The current-cash adapter deliberately accepts only the observed EUR configuration:
zero `degiroCash`, non-negative `totalCash` equal to `flatexCash`, exact cent units,
zero pending settlement, one agreeing EUR cash fund and `FLATEX_EUR` position.
Other fund currencies and FLATEX positions must be zero. Missing fields never
become zero. A duplicate name/currency/position or conflicting optional alias
blocks. Nonzero DEGIRO-held cash, negative cash and pending settlement need separate
evidence before broadening this policy; no inferred settled-cash subtraction.
An explicitly removed/ambiguous `isAdded` flag or mismatched wrapper name also
blocks; a full update must not treat removed rows as current values.

The client fetch start/end must both fall within the previous five minutes and
be ordered before the aware validation clock. This is a conservative operational
freshness policy, not a documented broker guarantee or proof of source cache age.
Saved snapshots cannot be replayed as fresh by using an old clock in operation.
The diagnostic saved-shape check used its original fetch-time clock explicitly
and is not current-cash acceptance.

`apply_cash_balance` defaults to DRY_RUN and invokes its supplied writer only
after strict successful-import evidence, no uncertainty and complete cash checks.
An invalid flag, ambiguous/failed import, unknown ledger category or stale data
blocks before any writer call. The callback is a functional boundary: the
orchestrator owns target URL validation, complete active-context reconciliation,
fresh target-account currency verification and binding the immutable core writer.
This pure gate adds no Ghostfolio HTTP request and does not activate CLI writes.

## Trade normalization policy

The pure adapter normalizes each execution independently using Decimal arithmetic.
An explicit ISIN-to-Yahoo mapping and independently verified Yahoo quote currency
are required inputs. Broker tickers never supply a fallback. Each comment is
`DEGIRO#<source-account>:TRADE:<execution-id>`; reconciliation also keys by target
account. Equal overlaps are retained once, while changed financial content under
an existing identity blocks the batch. Separate fills retain separate identities.

Only STOCK metadata with contract size 1 and characterized EUR/USD/JPY major
currencies are currently accepted. ETF, derivative, transfer and minor-unit cases
are blocked pending broker evidence. Price times signed quantity must reconstruct
the signed total within one security-currency quantum. Both gross FX rates must
reconstruct the base total within one base-currency quantum, with division from
security to base. Same-currency rates must be 1. Brokerage and AutoFX must both
be non-positive, and their sum must equal the total fee exactly. The activity fee
is the negated total base fee multiplied once by `fxRate`; `nettFxRate` is unused.
No refund clamping, automatic 100x scaling or hidden extra commission is applied.

Source timestamps require an explicit UTC offset and are converted to the same
instant in UTC, including local-to-UTC calendar-day shifts. JSON numbers are
finite; malformed financial input errors never include the original value.

The holdings guard consumes normalized activities and a complete, active target
snapshot supplied by future orchestration. An already imported execution must
match canonical financial content and is excluded from pending holdings changes.
Only the same target account and Yahoo symbol contribute to the holding baseline.
Pending executions are applied chronologically with no quantity epsilon; any
negative position blocks the batch. A nearby manual trade of the same account,
symbol and side blocks explicit reconciliation, regardless of quantity. Date
proximity never creates a broker identity in full-history/prospective modes.
Rolling mode applies the reviewed IBKR manual matching rules: closest same-account/symbol/side trade within2days and quantity
difference below0.001 is consumed once; same-account/symbol dividend within3days
is treated as represented. Canonical identities still require exact financial
content. See [the rolling contract](prospective-sync.md) for limits; these
heuristics are not historical accounting certification.
The guard is conservative: missing opening holdings and buys already represented
in a later current baseline can require operator reconciliation.

Offline regressions cover these boundaries with synthetic data. A separate local
arithmetic characterization against the existing private snapshot accepted all
three observed executions, using placeholder symbols and source currencies. It
made no network requests and does not establish Yahoo mapping validity, history
completeness, or authorization for import.

## Paid dividend normalization policy

Cash classification checks the complete ledger before constructing a dividend.
Reviewed YAML rules must match exactly one category, with validated row identities,
offset timestamps, required relations, financial signs and currencies. Equal
cash overlap rows may differ only in the window-derived balance.

`cash_sweep_annotation` describes Virement rows with null amounts and blank CSV
movement/currency fields. `cash_sweep_transfer` describes signed Degiro Cash Sweep
Transfer movements, which stay cash-only. These keys correct the initial inverted
neutral-sweep interpretation. Any future annotation with a financial amount blocks
classification. Observed zero-valued Flatex interest is still recognized as an
unsupported account-level blocker; zero is not an exemption from the supported policy.

A dividend and withholding must form a unique group on product, currency and exact
offset-aware payment/value-date instants. Multiple same-day payments at different
instants remain separate. Missing tax, isolated tax, multiple candidates, new
relation fields, reversal signs and mixed-currency tax block the batch. Untaxed
payments need separate broker evidence before relaxing the missing-tax guard.
Withholding must not exceed the gross payment.

The activity uses the gross paid amount as unitPrice, quantity 1 and the positive
linked withholding as fee, all in the verified instrument/Yahoo quote currency.
The comment is `DEGIRO#<source-account>:DIVIDEND:<payment-row-id>`; target account
remains part of the eventual dedup key. Current holdings, partial sales and upcoming
payments never enter this calculation. STOCK/unit/currency restrictions match the
trade gate; no amount or tax conversion is inferred for unsupported instruments.
A successful pure conversion does not override history, fee, cash or live-write gates.

The local immutable statement characterization now classifies all 88 movements and
finds the 10 observed unique dividend/withholding pairs without network requests.
Normalizing that full snapshot still fails at the preserved unsupported-category
account gate. Synthetic tests own regression coverage; private data stays off Git.
