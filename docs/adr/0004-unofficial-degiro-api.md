---
status: accepted
date: 2026-10-12
---

# Use the pinned unofficial DEGIRO API with strict refusal boundaries

Use the pinned reverse-engineered `degiro-connector` API for unattended reads;
the project is not affiliated with DEGIRO. Endpoints and response contracts can
break without notice, and automated access carries terms-of-use and account
blocking risk. Pin the reviewed dependency/source, monitor upstream changes and
require offline contract evidence before adoption. Keep exact approved origins
before credential-bearing requests, bounded calls and secret-free failures.

Unexpected relevant response shapes, identities or financial relationships stop
processing before dispatch. Refusing incompatible data is preferable to silently
dropping rows or inferring unsupported economics. API success and many overlapping
windows do not establish historical completeness.

Retained broker CSV statements are an independent reconciliation and recovery
fallback, not automatic replay or permission to import converter output. The
[CSV transition boundary](../v3-transition.md) records payment loss and fee
differences in a pinned external converter. Preserve statements privately and
review identities, dates, fees and overlap before any separately authorized
backfill. CSV-only unattended synchronization and speculative response adapters
are rejected because they lack the supported live evidence contract.
