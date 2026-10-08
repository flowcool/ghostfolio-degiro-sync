# ghostfolio-degiro-sync

Read [FINDINGS.md](FINDINGS.md) for the reconnaissance handoff, then the approved
[delivery plan](docs/plans/2026-10-08-degiro-sync.md) and
[CORE_PROVENANCE.md](CORE_PROVENANCE.md). Beads owns active execution state:
epic `infra-8tt.56`, metadata `project=ghostfolio-degiro-sync`.

## Architecture

- `degiro_to_ghostfolio.py`: DEGIRO fetch, broker-to-activity conversion, identities,
  existing-activity indexes, mapping, matching, URL policy and orchestration.
- `ghostfolio_core.py`: immutable broker-agnostic byte projection of the pinned
  IBKR source. Never hand-edit it or put broker-specific behavior into it.
- `scripts/check_core.py`: verifies the source projection and signals upstream
  main changes. `--write` is deliberate regeneration, not automatic propagation.
- The canonical IBKR sibling is read-only here. Review releases before repinning;
  do not modify it or extract a shared package. Later adoption of a standalone core in IBKR is separate work.

## Working commands

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main
```

Local core verification reads the pinned Git blob and local main without changing
the sibling. CI checks canonical remote main in disposable state. See provenance
for the exact propagation and rollback procedure.

## Conventions and gates

Functional Python, no custom classes or type hints. The explicit Option C
core/adapter split replaces the inherited mono-file convention. Follow
`.claude/rules/python-conventions.md` and `.claude/rules/security.md`.
Runtime dependencies remain pinned; dev-only pytest never ships in the image.
Every logic change has an offline regression. Pytest forbids network access;
real read-only characterization is a separate operator procedure.

DEGIRO_USERNAME, DEGIRO_PASSWORD, DEGIRO_TOTP_SECRET and GHOST_TOKEN come only from
`os.environ`, backed by an off-git SOPS store and pointer. Never log credentials,
OTP, session data, raw client details or auth responses. Validate the target URL
before any credential-bearing request; token exchange is outside scope.

Keep gates C1-C15 from the plan. Unverified cash categories, FX direction, history
completeness and current-cash semantics remain implementation gates. Unknown or
ambiguous relevant account data blocks writes. Default operational mode is DRY_RUN;
production mutations/cleanup/deployment require separate explicit authorization.

Git initialization, commit and push require Florent's explicit request, including
the first scaffold commit. Approval of implementation alone does not authorize them.
Until then preserve verified local artifacts and record their exact evidence in Beads.
