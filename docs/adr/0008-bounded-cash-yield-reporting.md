---
status: accepted
date: 2026-10-09
---

# Report only characterized zero interest and positive compensation

Retain zero EUR Flatex interest as INTEREST/MANUAL with quantity 1, price 0 and
fee 0. Report characterized positive cent-valued EUR monetary-fund compensation
as INTEREST/MANUAL with its credited amount and fee 0, using a distinct source
identity and symbol. This is a cash-yield reporting convention, not a legal or
tax classification or a claim that compensation is contractual bank interest.

Source identity, exact financial fields, independent CSV agreement and native
readback preserve the observed credit and separate same-day payments. Do not
invent gross amounts, tax, FX, a security dividend or a relationship to NAV rows.
Negative, nonzero-interest and uncharacterized relationships remain blocked.
Current cash is independently verified and set separately; imports must not
credit it again. Broad sign-based classification and omission of zero rows
would lose source evidence and are rejected.

The [cash-yield policy](../interest-compensation-policy.md) owns rationale,
source evidence, exact supported fields, synthetic proof and rollback. This
decision does not establish full-history completeness or authorize live writes.
