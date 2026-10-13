# Design

## Context

Existing behavior only.

## Goals / Non-Goals

No implementation.

## Decisions

- Broker rules: `degiro_to_ghostfolio.py` and `cash-rules.yaml`.
- Ghostfolio import, readback and cash update: `ghostfolio_core.py`, an immutable copy from sibling `ibkr_to_ghostfolio.py`.
- Rolling-mode matching with manual activities: adapted from IBKR (`pending_activities`).
- Schedule: `entrypoint.sh` with supercronic and five numeric fields, as in IBKR.
- Deployment differs between siblings. DEGIRO and BourseDirect ship `compose.yaml` and simulate when `DRY_RUN` is absent. IBKR ships no Compose file and writes when `DRY_RUN` is absent.
- Proof comes from offline tests and the retained real read-only DRY_RUN of 2026-10-10. A mode name proves nothing.

## Risks / Trade-offs

A simulation cannot prove production writes. Private captures cannot prove what DEGIRO keeps for every account.

## Migration Plan

Review before promotion; rollback with an atomic documentation revert.

## Open Questions

- DEGIRO retention limits and historical completeness are unproved.
- Ghostfolio acceptance of a zero INTEREST activity is unproved; it was only simulated.
