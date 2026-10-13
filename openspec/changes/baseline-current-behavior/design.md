# Design

## Context

Existing behavior only.

## Goals / Non-Goals

No implementation.

## Decisions

Retain `degiro_to_ghostfolio.py` and `cash-rules.yaml` for broker policy. Retain immutable `ghostfolio_core.py`, projected from sibling `ibkr_to_ghostfolio.py`, for import/readback and cash transport. Retain IBKR manual matching and isolated Apprise mechanisms; Compose/ENV/CRON follow both siblings. Reuse offline tests rather than infer guarantees from mode names.

## Risks / Trade-offs

Simulation cannot prove production writes; private captures cannot prove universal retention.

## Migration Plan

Review before promotion; rollback with an atomic documentation revert.

## Open Questions

DEGIRO retention limits and historical completeness remain unproved.
