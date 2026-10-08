# Observed DEGIRO contract

This extends the inspected connector contract in the approved plan. It describes
read-only evidence from 2026-10-08, not a guarantee of undocumented API behavior.
Private financial evidence stays outside Git. `cash-rules.yaml` owns repeated
classification strings; unexpected categories or ambiguity always block writes.

## Authentication and raw data

Unattended TOTP from the provisioned SOPS environment was verified. A bounded
session must preserve `degiro_connector.core.constants.headers.HEADERS` exactly.
Plain requests defaults on agentvm were redirected to `/myracloud-blocked/`.
The canonical connector headers restored login without following a redirect.
Login exceptions and diagnostics expose fixed codes only, never HTTP bodies.

The raw `cashMovements` fields observed include `id`, `type`, `description`,
`currency`, `change`, `date`, `valueDate`, `balance`, optional `productId`,
`orderId` and `exchangeRate`. Modeled cash responses would omit the extra fields.
Cash IDs are stable across wide/split reads. The `balance` field changes with
the requested date window; ignore only that field for overlap equality and never
use it as the current balance. All financial event fields must still agree.

## History and statement comparison

A single366-day window and overlapping90-day windows yielded identical sets of
3 execution IDs and88 cash IDs. Execution bodies matched exactly. Fourteen cash
rows differed only in derived `balance`. A same-day request returned the expected
one execution and six cash rows, proving both boundaries include that observed day.
No pagination, arbitrary look-back limit or absence of server truncation is proven.
No orders were returned for that year despite three executions: order history is
not a reliable substitute for executed-transaction history in backfill.

The separate CSV statement contained the same88 movements. Its timestamps match
the API's local offset timestamps (+01:00/+02:00), at minute precision; do not
silently reinterpret them as UTC. Value date, descriptions, product ISIN and order
reference agree. The CSV has UTF-8 bytes without a declared charset, so the
transport explicitly validates UTF-8 and sets the decoding before connector use.
Virement sweep annotations have no amount and blank CSV currency despite an API
currency value. Degiro Cash Sweep Transfer rows carry signed amounts and CSV
currency; they are cash-only movements, not nonfinancial notices. One trade differs by exactly one cent in the two cash views;
unrounded execution price times absolute quantity lies within one cent of both.
This is bounded display rounding evidence, not permission to hide arbitrary
financial discrepancies. Financial event IDs/counts and semantic fields remain
the completeness check; a new discrepancy fails reconciliation.

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

Interest and monetary-fund compensation are recognized but unsupported and block
account writes. Their policy belongs to `infra-8tt.56.14` by Florent's decision.
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

## Current cash

`account_info.data.baseCurrency` isEUR. `update` returns three named wrappers:
`portfolio`, `totalPortfolio`, `cashFunds`, each with a `value` list. The named
`totalPortfolio` values include `totalCash`, `degiroCash`, `flatexCash` and
`pendingSettlement`. Observed `totalCash = degiroCash + flatexCash`; `degiroCash`
is zero in this account. The EUR cash-fund value and `FLATEX_EUR` pseudo-position
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
proximity never creates a broker identity or silently suppresses an execution.
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
unsupported account-level blocker; zero is not an exemption from Florent's policy.

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
