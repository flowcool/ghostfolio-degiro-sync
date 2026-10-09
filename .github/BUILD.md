# Build and release guarantees

Every pull request, whatever its base branch (work is delivered as stacked PRs)
and including documentation-only changes, runs the offline Python regression
tests, an audit of the Python CI environment (`pip-audit`), native amd64 and
arm64 container builds with an isolated run-once and real cron smoke test, and
the core-integrity check (`scripts/check_core.py`, also weekly) that
`ghostfolio_core.py` is still the exact projection of the pinned IBKR source.
CodeQL analyzes Python independently. Dependency Review rejects newly introduced
moderate or worse dependency vulnerabilities, including development scope.
Required checks must pass before merging.

PR builds never log in to a registry or publish images, and no image publication
workflow exists yet: GHCR publication, the `main`-only `latest` tag and the weekly
no-cache rebuild used by the IBKR repository are introduced with the packaging
and deployment phase, with their own review. Nothing here deploys anything.

Runtime requirements pin the complete dependency closure. Dependabot proposes
weekly Python, Actions and Docker updates (a Python release is proposed once 14
days old; security updates ignore the cooldown). Supercronic is a separate
upstream binary: updating its version also requires both architecture checksums.
`ghostfolio_core.py` is never edited by hand and never bumped by Dependabot;
repin it deliberately with `scripts/check_core.py --write` after reading the
IBKR release notes. Never auto-merge dependency changes without the required
checks.

## Release notes

`release.yml` groups GitHub's generated notes by label. `pr-release-labels.yml`
adds `feature`, `fix`, `documentation`, `maintenance` and `breaking-change` from a
conventional PR title; it is advisory and never a required check. A
`breaking-change` or `compat` PR needs a filled "Release impact" section.

## CodeRabbit

`.coderabbit.yaml` enables automatic reviews for every base branch and draft
PRs, so stacked PRs are reviewed. Reviews beyond the plan's included hourly
allowance use usage-based billing once the trial ends; manage it in the
CodeRabbit billing settings. A CodeRabbit review is not a substitute for CI.

## Rollback

Revert a maintenance merge through a PR and wait for all required checks.
Repository administrators can temporarily disable a ruleset if a broken required
workflow prevents its own repair; restore it after the repair passes (see
`docs/github-setup.md`). No GitHub change deploys anything.
