# CLAUDE.md — ghostfolio-degiro-sync

DEGIRO → Ghostfolio sync modeled on `../ghostfolio-ibkr-sync`. The durable local
architecture and commands are in [AGENTS.md](AGENTS.md); active state is in Beads.

Start with [FINDINGS.md](FINDINGS.md), then the approved
[delivery plan](docs/plans/2026-10-08-degiro-sync.md) and
[CORE_PROVENANCE.md](CORE_PROVENANCE.md). Later decisions in the plan/provenance
override the historical handoff's mono-file reuse inventory.

## Architecture

| Fact | Value |
|---|---|
| Data source | `degiro-connector` (private DEGIRO API) — transactions_history + account_overview |
| Backfill / fallback | `dickwolff/Export-To-Ghostfolio` DEGIRO CSV converter (V3) |
| Auth | username + password + **TOTP secret** (unattended via `pyotp`) — secret available (Florent, 2026-10-08) |
| Runtime | mirror IBKR: `python:3.12-slim` + supercronic cron, Docker amd64/arm64 |
| Ghostfolio core | Option C: immutable pinned byte projection in `ghostfolio_core.py`; imported by separate DEGIRO adapter; anti-drift CI and human propagation |
| Deps delta vs IBKR | add `degiro-connector` + `pyotp` |

## Conventions (inherited from IBKR)

- `.claude/rules/python-conventions.md` — approved core/adapter split, functional, no type hints/classes, never log credentials.
- `.claude/rules/security.md` — credentials from `os.environ` only; private-API breakage is expected.
- Python style, pinned `requirements.txt`, offline `pytest` in `tests/`, DRY_RUN before writes.

## Git

Florent authorized autonomous commits, branches, PRs, merges and releases for
the approved scope. The repository is `flowcool/ghostfolio-degiro-sync`.
Request an actual CodeRabbit review of each final PR head and verify required
CI before merge. Production financial writes, cleanup and deployment still
require separate explicit authorization.

## Durable work state

- Epic `infra-8tt.56`, child of `infra-8tt`, with metadata `project=ghostfolio-degiro-sync`.
- Parent context: the ghostfolio epic `infra-8tt` tracks the IBKR sync and the broader Ghostfolio work.
