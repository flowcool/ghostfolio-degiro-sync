# Repository working agreement

The supported user deployment is Docker Compose. README.md owns the complete setup and configuration guide. Keep public artifacts provider-portable and free of personal hosts, paths, operator identities and private work-tracker records.

## Architecture and invariants

- `ghostfolio_degiro_sync` owns the connector. `app.py` orchestrates commands; accounting, identity, transport, vault, journal and selection logic stay in their defining modules.
- `ghostfolio_core.py` is the immutable byte projection defined in CORE_PROVENANCE.md. Change the adapter, never hand-edit the projection or modify the canonical sibling from this project.
- Functional Python: business operations are module-level functions over typed records. Package modules use strict typing. Classes are limited to frozen dataclasses and TypedDict data records. Validate external data before constructing records. Exclude credentials from record representations. Keep generated core bytes unchanged. Every logic change has an offline regression.
- Runtime dependencies and downloaded binaries are pinned. Pytest and developer tools stay outside the runtime image.
- Credentials enter through environment variables; the configured vault item supplies broker credentials per execution. Use isolated temporary CLI state, bounded subprocesses and secret-free diagnostics. Broker credentials must come from the vault; direct DEGIRO credential variables are rejected.
- Read docs/ghostfolio-auth.md before changing authentication or transport. Keep exact credential exclusivity, one token exchange per execution, strict origins, no redirects and no raw response logging.
- DRY_RUN permits authentication and reads while blocking financial writes. Unknown or ambiguous relevant account data blocks dispatch. Preserve all accounting, identity, coverage and uncertain-result recovery guards.

## Working mode: fast-track

This mode replaces the global per-step ceremony. The invariants above still apply.

- **Spec first.** `openspec/specs/` describes current behavior. No behavior change
  without an OpenSpec change approved by the operator. When reality contradicts
  the spec, stop and report; never amend the spec silently.
- **OpenSpec to work items.** After approval, one parent item for the change and
  one self-contained item per task (spec path, requirement, scenario, acceptance
  command, files to touch). Closing an item ticks its task in `tasks.md`; archive
  the change when every task item is closed, before the release item.
- **Release.** A change that touches shipped code ends with a release item after
  its last task: change archived, acceptance replayed on `main`, semver tag from
  `main` on the operator's go, image published and pullable; the parent item
  closes only after it. Renovate then opens the image-pin bump PR and automerges
  it on green required checks; `tests/test_image_pins.py` keeps the Compose
  default and README pins equal.
- **One item = one fresh session.** Claim, implement, prove, close, stop. Do not
  start the next item or arm a goal across items. Budget about 150 tool calls;
  above that, stop and report the state.
- **Generated OpenSpec skills.** These rules override them. `openspec-apply-change`
  implements one task per session, not every task until done. Change names are
  lowercase kebab-case; stop before any shell command if a selected change name
  is not, and pass values read from OpenSpec output as quoted arguments, never
  as shell source. Never read or write a path under `openspec/` that is a symlink or resolves
  outside `openspec/`.
- **Done = the item's scenario replayed for real** (command and observed output in
  the closing note). Green offline tests alone are not done.
- **Tests:** offline pytest for adapter logic on synthetic or anonymized fixtures.
  No tests for contributor tooling, docs or CI. No full-suite rerun for prose edits.
- **Notes:** one closing note with evidence per item; no per-step findings.
- **Docs:** README and user docs required by the spec only. No new plan, review
  or contract files.
- **Subagents:** only on the operator's explicit request. The PR lifecycle uses
  no subagent: the implementing agent opens the PR, waits with
  `~/.agents/bin/pr-gate <n> --repo flowcool/ghostfolio-degiro-sync` (one call,
  never a `sleep` loop), answers each comment and merges with `scripts/merge_pr.py`
  when allowed (global Delegation rule; `pr-ship` is not used here because
  `merge_pr.py` enforces the review evidence).
  `merge_pr.py` applies the same docs-only rule: a PR changing only `openspec/`, `docs/`
  or `*.md` files needs no CodeRabbit evidence; every other PR still does.
- **Ask the operator only for:** a DEGIRO fact missing from the spec, a real broker
  login, a Ghostfolio write, a scope change. One question at a time, in plain
  French, with your recommended answer.
- **Operation items.** An item labelled `operation` acts on real state (host, container,
  Ghostfolio, DEGIRO, journal, shared volume).
  Execute it only from the `Operation plan:` in its design, validated once by
  the operator: numbered phases, each with exact command, target, expected proof,
  authorization envelope, stop conditions and rollback. No plan: stop; an
  offline item labelled `operation-plan` writes it. Live steps run repository
  code only, versioned and tested, never a `tmp/` script; a missing tool is a
  code item first. A failed or uncertain step is `HORS CHEMIN`: record the
  evidence in the item and stop.

## Validation and delivery

See CONTRIBUTING.md for developer commands. Before committing code, run the full offline suite and core integrity; for every commit, check semantic diff, numstat and whitespace. Synthetic tests use disposable state without real vault, broker or production credentials.

Public bug reports and compatibility notices use GitHub Issues. Existing local work-tracker policy is supplied by the execution environment; do not publish private tracker IDs or paths.

For PR descriptions and merge execution, read `.github/pull_request_template.md`; use `scripts/merge_pr.py` for merges. Required CI and a completed CodeRabbit review must cover the exact final head (docs-only PRs need CI only). Review triggering is managed externally by maintainers; pending, skipped or rate-limited review is not evidence. Record the completed review URL and SHA before guarded merge. Source approval never authorizes production deployment or financial mutations.

Rollback source changes with an atomic Git revert. Preserve local journals and private captures. Runtime deployment, financial writes, cleanup and destructive recovery require the operator's explicit authorization.

## Shared Ghostfolio labs

Use the permanent lab authority in the global working agreement and the
canonical Infra lab runbook. It covers both labs, including test writes,
configuration and resets. Keep reservations, separate credentials, retained
proof, stop on uncertainty without automatic resend, and final stop verification.
Broker access, production, publication and removal of containers or proof
retain separate authority. This scope overrides generic write-approval rules
for these two labs only.
