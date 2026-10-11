# Contributing

User deployment is supported through Docker Compose only; see README.md. The host interpreter commands below are for development and offline verification.

## Offline checks

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main
git diff --check
```

Pytest forbids network access. Use synthetic credentials and financial fixtures. Never load a real vault, broker account or shared production database into tests. Core integrity reads pinned Git objects without modifying the sibling; CI fetches the canonical source in disposable state. CORE_PROVENANCE.md owns the pin and exact propagation procedure.

## Native container validation

CI builds amd64/arm64 images, checks pinned binaries, audits dependencies and runs isolated run-once/cron smoke tests. Local contributors can build and run the same synthetic smoke on their own Docker daemon:

```sh
# Supply synthetic Compose values first; this overlay is for contributors only.
docker compose -f compose.yaml -f compose.build.yaml build
.venv/bin/python scripts/smoke_container.py ghostfolio-degiro-sync:local
# Direct native build is also available for smoke validation:
docker build --build-arg TARGETARCH=amd64 -t degiro-smoke:local .
.venv/bin/python scripts/smoke_container.py degiro-smoke:local
```

Use arm64 on an arm64 host. The smoke has no broker or vault access. Account credentials and encrypted provider-specific loaders are not developer fixtures.

## Optional synthetic Ghostfolio lab

compose.lab.yaml is a separate project with an internal network and dedicated database volume. It uses reviewed Ghostfolio/Postgres/Redis pins and public synthetic broker fixtures. Its quote/profile seam replaces remote quote lookup only; native import/readback and database behavior remain intact. Configure lab-only environment variables and private mounts, then use scripts/prepare_lab.py and scripts/run_compose_lab.py with their `--help` descriptions. These are contributor tools, not another supported deployment mode.

Never connect the lab to a production network or provide real vault/broker credentials. Preserve its volume until the positively owned resources are explicitly removed. Normal stop/restart keeps data; resetting it is a separate destructive operation. Native scenario evidence is in docs/isolated-acceptance.md.

## Upstream maintenance and review

Read docs/upstreams.md. Scheduled watches create public compatibility notices without changing pins or deployments. Review upstream source, update synthetic contract fixtures and record evidence before adopting changes. Development tools follow functional Python with no custom classes/type annotations.

Use the pull-request template. CI and completed CodeRabbit coverage must apply to the final head before the guarded scripts/merge_pr.py command. Keep personal paths, hostnames, operator names, captures and private issue references out of public artifacts.

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
  ghcr.io/flowcool/ghostfolio-degiro-sync:v0.2.0 python /journey/community_journey.py
```

Use `ghostfolio-degiro-sync:local` for the contributor build. The runtime image
contains no test framework. A release's exact digest must pass the same harness
from a clean clone before community publication is considered verified.
