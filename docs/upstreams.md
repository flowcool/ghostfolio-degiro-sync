# Upstream inventory and monitoring

Every consumed source or dependency has a reviewed pin and a monitoring path.
A notice starts a human compatibility review; no watcher repins code, upgrades an
image, merges a dependency PR, deploys a service or accesses financial accounts.

| Upstream | Consumption / reviewed pin | Monitor |
| --- | --- | --- |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | Destination API; lab Dockerfile pins3.81.0 and its digest; actual operator version is independent | Daily release watch07:17UTC, baseline3.81.0 included; Dependabot lab image |
| [IBKR sync](https://github.com/flowcool/ghostfolio-ibkr-sync) | Immutable core byte projection, commit in CORE_PROVENANCE.md | Daily source watch07:41UTC plus weekly core-integrity check |
| [degiro-connector](https://github.com/Chavithra/degiro-connector) | Runtime3.0.36; exact wheel/tree/source in docs/connector-provenance.yaml | Daily PyPI releases and daily source watch; Dependabot and audit |
| [Export-To-Ghostfolio](https://github.com/dickwolff/Export-To-Ghostfolio) | Contributor-only native CSV converter reference, pinned in tests/fixtures/degiro_v3_transition.yaml; Node image recorded there | Daily default-branch source watch; recorded Node image is fixture provenance, deliberately regenerated after review |
| [Bitwarden CLI OSS](https://github.com/bitwarden/clients) | Separate runtime executable2026.9.1 with both architecture SHA256 pins in Dockerfile; GPL/source notice in third_party/bitwarden | Daily dependency watch07:29UTC filters cli-v releases; native security/smoke checks |
| [Supercronic](https://github.com/aptible/supercronic) | Runtime scheduler version and architecture SHA256 pins in Dockerfile | Daily GitHub releases; full-image advisory scan |
| Python runtime and its complete closure | requirements.txt pins DEGIRO, PyOTP, requests, YAML, Apprise and every transitive package | Daily PyPI releases; weekly Dependabot; pip-audit on PR/release/weekly checks; blocking image scan |
| Python developer/CI tools | requirements-dev.txt pins pytest; checks.yml pins pip-audit | Daily dependency releases; weekly Dependabot; complete CI environment audit |
| Python/Debian base image | Digest-pinned Python3.12 slim in Dockerfile, OS packages inherited from it | Weekly Docker Dependabot and native image security checks |
| PostgreSQL/Redis contributor lab | Digest-pinned images in compose.lab.yaml | Weekly Docker Dependabot at root; lab isolated from production |
| GitHub Actions: checkout/setup-python, CodeQL, dependency-review, Trivy, Docker build/login, artifacts | Exact SHA in workflows | Weekly Actions Dependabot; reviewed CI and native scan gates |

The optional operator notification destinations, Docker Engine/Compose, existing
Ghostfolio service and external vault server are supplied by the operator. This
repository does not deploy or pin those external services. Bitwarden/Vaultwarden
HTTPS authentication and CLI behavior are validated through synthetic contracts;
the vault URL is an explicit known configuration input. Vaultwarden server upgrades
are an operator responsibility, while the shipped CLI is monitored here.

## Notice and adoption contract

Release/source watches run on main with contents:read and issues:write only.
They paginate bounded public metadata, acknowledge markers in both open and closed
issues, ignore PR markers and create at most ten notices per run. Failed upstream
reads abort before creating notices; a failed POST stops without blind retry.
Untrusted release-note prose is linked rather than copied into issues. Requests
have deadlines, refuse redirects, disable ambient proxies and hide response data.

The Ghostfolio checklist covers account listing, activity identity/pagination,
imports and deduplication, balances/body whitelist, and Security Token exchange.
The baseline is the pinned lab contract, not a claim that every newer version works.
Dependency notices flag major/minor/patch changes. Source notices link exact pinned
and observed revisions. Review consumed behavior, add offline fixtures, retain the
pin or adopt through a tested PR. Immutable core regeneration remains deliberate
under CORE_PROVENANCE.md. Financial semantics and unknown-data gates remain intact.

Dependabot security updates bypass the ordinary14-day Python cooldown. The weekly
checks rerun vulnerability scans even without source changes. Supercronic's existing
Go-stdlib exception is constrained to the scheduler binary and accompanied by an
advisory scan; Bitwarden is covered by the blocking image scan. PRs and releases
still require the exact final-head CI and CodeRabbit evidence before integration.
