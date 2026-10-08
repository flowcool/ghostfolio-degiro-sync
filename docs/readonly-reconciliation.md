# Observed private-source reconciliation boundary

Read-only characterization on 2026-10-09 (Europe/Zurich) followed the authoritative
infra CMDB and Ghostfolio Compose to the owning UGreen host. Runtime package
version was 3.81.0. An existing environment-only bearer in the owning IBKR runtime
performed exactly GET `/api/v1/account` and GET `/api/v1/activities` on the approved
private origin. No token exchange, financial mutation, deployment, scheduler run
or production test occurred. Raw data was captured locally in ignored private
files with mode 0600; bearer credentials stayed in the remote process environment.

The complete response contained 1,017 activities across six accounts. The DEGIRO
target had 145 rows, an unredacted balance and EUR currency. The adapter accepted
the complete financial/ownership context, retaining unrelated provider rows.
This proves compatibility with that saved response, not current write readiness.

The canonical external converter's output directory contained a V3 JSON produced
on 2026-07-16, with four dividends. Every row matched exactly one existing target
activity on all ten canonical DTO fields: account, comment, currency, data source,
UTC instant, fee, quantity, symbol, type and price. The four matched created IDs
were distinct. No proximity, rounding or inferred currency was used. This is an
actual output comparison, not a new converter run or permission to adopt entries.
The output metadata records version `v0` and a generation date on 2026-07-16;
it does not identify an immutable converter revision. The original input directory
was empty, so the source CSV, exact producer revision and complete historical
coverage could not be independently reconstructed.

A fresh bounded broker read of 2025-10-08..2026-10-08 returned three executions,
88 cash movements and 88 rows from the alternate authenticated CSV-report endpoint.
Ten dividend/withholding pairs remained uniquely associated. Count agreement and
that alternate API export do not prove an independent manual statement or unlimited
history. `history_completeness_verified` remains false.

The full ledger contains four Flatex interest rows and one monetary-fund
compensation row. Dividend normalization and current-cash acceptance both stop
at the unsupported-category gate. No successful real synchronization DRY_RUN or
cash acceptance is claimed. Do not discard these rows, fabricate completeness,
borrow a quote-unit mapping, or clear uncertain state to make the preflight pass.
An explicitly approved policy for unsupported rows, independent statement/V3
provenance and explicit request-bound recovery remain prerequisites. See [the source contract](source-contract.md),
[synchronization](synchronization.md) and [isolated acceptance limits](isolated-acceptance.md).
