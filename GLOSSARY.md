# DEGIRO account synchronization

Synchronization translates supported DEGIRO financial evidence into Ghostfolio
activities and current cash for one explicitly selected account pair.

## Language

**Source account**: The DEGIRO account whose executions, cash movements and
holdings provide the financial evidence.
_Avoid_: account (when ownership is ambiguous)

**Destination account**: The Ghostfolio account selected to receive activities
and current cash from the source account.
_Avoid_: account (when ownership is ambiguous)

**Execution**: A completed broker trade with a stable identity and exact financial
evidence; an order is not proof of an execution.
_Avoid_: order, transaction (when referring specifically to a trade)

**Cash movement**: A broker ledger event whose category, identity and financial
fields determine its accounting treatment; its historical balance is not current cash.
_Avoid_: current cash, activity

**Activity**: A destination financial event representing a supported execution,
paid dividend, standalone fee or characterized cash yield.
_Avoid_: cash movement, order

**Proposal**: The supported activities still missing from the destination plus
verified current cash, before any financial dispatch.
_Avoid_: accepted import, synchronization success

**Accepted import evidence**: Exact evidence of the activities accepted for a
particular import; transport success alone is insufficient.
_Avoid_: successful request, HTTP success

**Current cash**: The source account's fresh, verified available cash observation,
with supported currency and settlement conditions.
_Avoid_: ledger balance, historical cash balance

**Write intent**: An account-owned record of a specific intended financial request
that remains pending until its completion is confirmed.
_Avoid_: retry token, completed activity

**Uncertain result**: A financial request whose complete accepted outcome is not
established; absence from readback does not prove non-delivery.
_Avoid_: failed write, safe retry

**Positive import readback**: Complete destination evidence matching every expected
activity and its ownership for one selected pending import.
_Avoid_: cash recovery, cancellation proof

**Local confirmation**: Confirmation of a selected pending write intent in local
state; it neither sends a financial request nor undoes one.
_Avoid_: replay, financial rollback

**Rolling coverage**: The successfully completed source interval recorded for
bounded rolling synchronization, without a claim of complete history or cost basis.
_Avoid_: historical completeness, baseline

**Prospective cutover**: A proved opening instant separating protected prior
history from the interval reconstructed by prospective synchronization.
_Avoid_: rolling checkpoint, historical completeness

**Durable account execution**: The account-owned sequence that records write
intent, establishes accepted outcome and retains uncertainty across restarts.
_Avoid_: automatic retry, generic persistence
