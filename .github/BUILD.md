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

PR builds never log in to a registry or publish images. `release-image.yml`
publishes only a published semantic-version GitHub Release whose tag is on main.
Its serialized preflight authenticates to the registry without requiring a
package to exist already. Failure diagnostics report only the phase and HTTP
status, never credentials or response bodies.
Each native architecture is built, scanned and smoke-tested before publishing by
digest with SBOM and build provenance. This creates the package on its first
release without creating or changing a version tag. The final job then proves
the version tag is absent before assembling the two digests, verifies amd64/arm64
and records the manifest. Existing version tags and ambiguous registry failures
abort publication of the version manifest.
Only the current stable release can update `latest`; prereleases cannot do so.
A release rerun never silently overwrites an existing version. Runtime code,
Bitwarden artifacts and architecture checksums remain pinned. No workflow deploys.

Community Compose pulls a published version or digest. Contributor builds use
`compose.build.yaml`; they do not publish. Capture the currently installed
RepoDigest before an upgrade, stop the scheduler, change DEGIRO_IMAGE, pull and
recreate; restore that saved digest to roll back. Preserve mapping and the complete
state/journal directory. Source/image rollback never undoes financial records.
See [recovery](../docs/recovery.md) for interrupted-request handling.

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
