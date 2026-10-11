# Synchronization configuration

The complete Docker Compose setup, credentials, mapping, scheduling and user variables are documented in the root [README](../README.md).

Normal synchronization uses SYNC_MODE=rolling and a 90-day window through the current Europe/Zurich date. Default DRY_RUN=1 proposes activities/cash and sends no financial writes. Authentication POSTs, account locking and local journal creation are allowed in simulation.

Supported executions, paid dividends/taxes, characterized standalone fees, cash yield and fresh EUR cash retain the source contracts described in [source-contract.md](source-contract.md), [fee-contract.md](fee-contract.md) and [interest-compensation-policy.md](interest-compensation-policy.md). Unknown or ambiguous relevant data blocks the account.

The advanced [operating contract](prospective-sync.md) describes duplicate matching, coverage, bounded catch-up and prospective cutover evidence. It does not certify historical completeness or cost basis. See [recovery](recovery.md) for interrupted imports; do not erase state to permit replay.
