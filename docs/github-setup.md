# GitHub setup

The sibling IBKR repository supplies the Actions SHA pins, merge policy, security
settings, Dependabot grouping, release categories and release-label workflow.
Run `python scripts/configure_github.py` for a read-only preview; `--apply` requires
operator authorization. Save pre-change settings with `--snapshot tmp/settings.json`.
Restore only changed fields from that snapshot using the corresponding GitHub API;
remove new rulesets by their exact IDs only with destructive-action authorization.

Main requires pull requests, resolved review threads, offline tests, dependency
audit/review, CodeQL and core integrity. Force pushes and deletion are blocked.
Initial branch creation is permitted because hosted checks need the first push.
Version tags cannot be updated or deleted. Workflow permissions default to read;
all actions require SHA pins. Secret scanning, push protection, Dependabot security
updates and private vulnerability reporting mirror IBKR.

Container checks and GHCR publication are introduced by the packaging phase once
the Dockerfile exists. Add both `container-check (amd64)` and `container-check
(arm64)` as required checks at that time. No image publication workflow is enabled
by this bootstrap. Dependency/upstream watcher automation is introduced alongside
its tested helper scripts in that phase. Release immutability and external-fork approval policy mirror the actual sibling
settings through their API endpoints; recheck them before the first publication.
The default branch can be changed only after the first push to an empty repository.

Repository creation does not authorize the first commit, push, release or deployment.
Hosted checks require an explicitly authorized first push. Local tests remain offline.
