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

## Extended historical read-only characterization

A direct operator collection requested 2000-01-01..2026-10-08 in overlapping
366-day windows, then reread the occupied 2019-04-25..2026-10-08 span in overlapping
90-day windows. Both requests returned the same full authenticated CSV statement.
Private archives live outside project repositories under
`~/.local/share/ghostfolio-degiro-sync/history/`, with directories 0700, files 0600,
per-response captures, a decoded UTF-8 CSV and SHA256 manifests. Authentication
responses, headers, session URLs and client-details responses were not archived.

The earliest observed movement was 2019-04-25 and the latest 2026-10-06.
Nineteen annual pre-activity overview windows returned HTTP 200 with `data: {}`,
without `cashMovements`. The runtime correctly rejects this missing collection.
A temporary read-only characterization collector preserved those envelopes and
continued collection; it did not change the runtime or authorize synchronization.
Empty ancient windows do not establish unlimited look-back or account inception.

Across both widths, all 70 complete executed-transaction bodies agree. The 1,001
cash rows with nonzero IDs also agree exactly after excluding the already observed
window-derived `balance`. However, legacy `CASH_FUND_NAV_CHANGE` rows all have ID
`0`: the annual capture contains 339 distinct bodies, the split capture 318.
Of these, 150 annual-only and 129 split-only bodies differ between widths; every
such difference is a 2019/2020 NAV event. These are not stable independently
identifiable activity records. Never collapse them by ID, invent broker IDs,
ignore their financial changes or infer an import policy from type alone.
The strict runtime overlap check blocks distinct rows sharing ID `0`.

The full CSV has 1,366 rows after its header, including three undated footer rows.
An exact multiset comparison of date/minute, value date, ISIN, description,
movement currency/amount and order reference matches 1,254 API rows. Another 83
unique pairs differ by exactly one cent (81 NAV rows, two executed-trade cash rows);
three pairs agree on those fields except description. The CSV also contains 23
additional zero-valued NAV rows. These findings are recorded discrepancies, not
accepted rounding or description-normalization rules. No successful statement
reconciliation or complete-history flag is claimed.

Annual order history also contains a repeated order identity with changed content;
order snapshots remain diagnostic, never executed-activity identities. Temporary
merged diagnostic snapshots can contain extra rows after a partial failed merge.
Their counts are not authoritative: comparisons above use the preserved individual
window responses and exact body sets, with no broker mutation or Ghostfolio request.

The fresh direct export enables a new source-pinned CSV transition investigation;
it cannot recover the exact producer or omitted input of an old July backfill.
Unsupported legacy fund behavior remains outside the approved import policy,
alongside the interest/compensation gate. History verification remains false.

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

## Import format diagnostics

The operator distinguishes the supported financial contract from recognized legacy
fund markers and unknown/incompatible response shapes. No broker-provided format
version or calendar cutoff has been proved: a compatible 2019 payload uses the
same checks as one dated 2026. `CASH_FUND_NAV_CHANGE` and `CASH_FUND_TRANSACTION`
produce a legacy monetary-fund format error; missing/nonfinite execution fields
and nonpositive FX rates produce separate incompatible-contract errors. A zero
rate is not automatically evidence that an API response is old.

Errors are fixed strings, preserved through the sanitized broker reader and both
CLI modes. Unknown envelopes, including ancient `data: {}`, are never converted
to empty history. Known legacy detection stops before merging cash events or any
financial dispatch; preflight still validates the entire account afterward for
compatible shapes. No missing amount, identity, currency or rate is synthesized.
Read-only diagnostics still guarantee logout and retain credential privacy.
Future historical support is separately tracked; these messages do not broaden
import support or authorize a cash/category exception.

## Historical scope extension findings

The full raw-window stable set contains 110 paid dividend rows and 112 withholding
rows. Exact product/currency/payment/value-date grouping yields 95 unique pairs.
The remaining groups contain 15 payment-only rows, 13 tax-only singletons and two
tax-only double groups. Nine payment-only rows have exactly one same-product,
same-currency, same-calendar-day candidate with equal value date: eight timestamps
differ by one second and one by four seconds. Each candidate/payment appears
exactly once with its own financial fields in the retained CSV, at the same local
minute. This corroborates the recorded rows, not an explicit payment reference.
Five payments have no same-day withholding candidate and all use HKD; one has two
candidates. Five isolated withholding rows are positive. The current exact-match,
missing-tax and reversal guards remain intact; no tax is inferred or summed.

A separate offline per-execution arithmetic diagnostic used placeholder symbols
and broker currencies, not independently verified Yahoo quotes. Of 70 STOCK
executions (41 BUY, 29 SELL), 34 passed the existing converter. The other outcomes
were 18 invalid FX rates, three flagged transfers, five absent/invalid financial
values, six uncharacterized currency-unit cases and four inconsistent side/sign
cases. These are refusal outcomes, not diagnosed financial errors or permission
to synthesize missing values. The source currencies were EUR, USD, JPY and CAD.
No holding, quote mapping, full-source acceptance or financial write was proved.

The broader stable ledger contains 16 Flatex interest rows, all zero, and one
positive monetary-fund compensation. Unknown legacy fund events and every existing
unsupported category still block the whole account. A follow-up policy proposal
is separate from the approved implementation; it must be reviewed before changing
these boundaries. See [the proposed contract extension](plans/history-contract-extension.md).

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
