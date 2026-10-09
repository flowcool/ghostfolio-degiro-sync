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
`.claude/rules/python-conventions.md`, `.claude/rules/security.md` and
`.claude/rules/delegation.md` (fleet delegation, model right-sizing, infra handoff).
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

Florent explicitly authorized autonomous commits, branches, PRs, merges and
releases for the approved implementation scope on 2026-10-08. Verify required CI
and a completed CodeRabbit review covering the exact final head SHA before merging.
Record the review URL and reviewed SHA in Beads and the PR. Skipped, pending or
rate-limited reviews are not evidence. Florent manages hourly review triggers
externally; do not schedule or repeat them here. Production financial mutations,
cleanup and deployment retain their separate explicit authorization gates.

For PR bodies, including skill-generated bodies, use the compatible sections in
[the PR template](.github/pull_request_template.md); it also owns the read-only
merge-preflight command and exact-head handoff procedure.

## Execution continuity

When Florent requests autonomous execution, carry the agreed scope across task,
commit and PR boundaries. A completed subtask or a pending external review is a
progress update, not a reason to end the turn: select the next independently
actionable authorized task. Do not require another "continue" message. Stop only
when the authorized scope is complete, indispensable information is unavailable,
or the next action requires an explicit authorization that has not been granted.
An explicit pause request wins: finish only the current task when Florent permits
that completion, reconcile durable state, then pause without selecting more work.
Keep the review-before-merge and production authorization gates above.

## Agent skills

### Issue tracker

Issues are tracked in the shared Beads database, scoped with `project=ghostfolio-degiro-sync`. See `docs/agents/issue-tracker.md`.

### Triage labels

The canonical triage roles use the default label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.
