# Contributing

User deployment is supported through Docker Compose only; see README.md. The host interpreter commands below are for development and offline verification.

## Architecture context

Read [docs/architecture.md](docs/architecture.md), [GLOSSARY.md](GLOSSARY.md)
and the relevant [architecture decisions](docs/adr/) before changing module
responsibilities, financial execution or recovery.

## Offline checks

Package modules use strict typing and frozen dataclass or TypedDict records.
Validate external input before constructing records. Keep business operations
as module-level functions and exclude credentials from record representations.
Legacy modules keep their style until extraction. Generated core bytes remain
read-only and outside formatting and type-checking changes.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/check.sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main
git diff --check
```

Use Python 3.14 for development, matching the image and CI. Pytest forbids network access. Use synthetic credentials and financial fixtures. Never load a real vault, broker account or shared production database into tests. Core integrity reads pinned Git objects without modifying the sibling; CI fetches the canonical source in disposable state. CORE_PROVENANCE.md owns the pin and exact propagation procedure.

## Native container validation

CI builds amd64/arm64 images, checks pinned binaries, audits dependencies and runs isolated run-once/cron smoke tests. The smoke checks Python 3.14 and native dependency execution on each architecture. The runtime image contains no pip or developer tools. Local contributors can build and run the same synthetic smoke on their own Docker daemon:

```sh
# Supply synthetic Compose values first; this overlay is for contributors only.
docker compose -f compose.yaml -f compose.build.yaml build
.venv/bin/python scripts/smoke_container.py ghostfolio-degiro-sync:local
# Direct native build is also available for smoke validation:
docker build --build-arg TARGETARCH=amd64 -t degiro-smoke:local .
.venv/bin/python scripts/smoke_container.py degiro-smoke:local
```

Use arm64 on an arm64 host. The smoke has no broker or vault access. Account credentials and encrypted provider-specific loaders are not developer fixtures.

## Upstream maintenance and review

Read docs/upstreams.md. Scheduled watches create public compatibility notices without changing pins or deployments. Review upstream source, update synthetic contract fixtures and record evidence before adopting changes. Contributor scripts outside the package keep functional Python without custom classes or type annotations.

Use the pull-request template. CI and completed CodeRabbit coverage must apply to the final head before the guarded scripts/merge_pr.py command. Keep personal paths, hostnames, operator names, captures and private issue references out of public artifacts.

The guarded command defaults to a merge commit. Select another method explicitly:

```sh
.venv/bin/python scripts/merge_pr.py <number> --method squash
# --method accepts merge, squash or rebase.
```

The selected method must be enabled by both repository settings and every
effective rule on the PR's base branch. A failed or incomplete policy lookup
blocks the command. Every method keeps the verified final-head review/CI checks
and `--match-head-commit` pin; there is no auto-merge or administrator bypass.

## Complete community journey in a disposable container

The public synthetic harness uses the real connector, vault retrieval and sync
orchestration, substituting only CLI results and HTTP responses. It exercises
account discovery and a rolling DRY_RUN proposal, with fresh vault state, private
files and zero financial writes. No network, real secrets or production mounts:

```sh
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --mount type=bind,src="$PWD/scripts/community_journey.py",dst=/journey/community_journey.py,readonly \
  --mount type=bind,src="$PWD/tests/fixtures/degiro_contract.yaml",dst=/journey/degiro_contract.yaml,readonly \
  ghcr.io/flowcool/ghostfolio-degiro-sync:latest python /journey/community_journey.py
```

Use `ghostfolio-degiro-sync:local` for the contributor build. The runtime image
contains no test framework. For release verification, replace `:latest` with
the published exact digest; that digest must pass the same harness from a clean
clone before community publication is considered verified.
