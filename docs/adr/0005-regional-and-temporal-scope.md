---
status: accepted
date: 2026-10-12
---

# Keep synchronization within the characterized regional and temporal scope

Rolling and prospective synchronization request statements with country/language
`("fr", "fr")`; this is fixed in `run_sync_locked`, not inferred from the account.
Cash descriptions and associations are characterized for French statements.
Compose and broker-local date boundaries use Europe/Zurich. Support EUR, USD and
JPY quote currencies and current EUR cash only; other locales, cash currencies
and units require independent characterization rather than configuration alone.

Normal Compose operation uses a rolling 90-day inclusive window through today,
with explicit bounded catch-up for coverage gaps. It verifies recent evidence,
holdings and current cash without reconstructing full history or cost basis.
Prospective mode requires a separately proved cutover; full-history writes require
explicit completeness evidence that the live reader does not establish.

Existing imported activities are never automatically corrected or deleted:
changed canonical financial evidence blocks work. Retain ownership, write intent,
uncertainty and coverage guards. Universal locale detection, full-history claims
from narrow windows and automatic financial repair are rejected because they
would widen accounting and recovery promises beyond the observed contracts.
The [mode contract](../prospective-sync.md) owns detailed evidence requirements.
