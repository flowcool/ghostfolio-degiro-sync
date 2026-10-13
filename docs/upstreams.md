# Upstream inventory and monitoring

Every consumed source or dependency has a reviewed pin and a monitoring path.
A notice starts a human compatibility review; no watcher repins code, upgrades an
image, merges a dependency PR, deploys a service or accesses financial accounts.

| Upstream | Consumption / reviewed pin | Monitor |
| --- | --- | --- |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | Destination API; lab Dockerfile pins 3.81.0 and its digest; actual operator version is independent | Daily release watch 07:17 UTC, baseline 3.81.0 included; Renovate lab proposals require approval |
| [IBKR sync](https://github.com/flowcool/ghostfolio-ibkr-sync) | Immutable core byte projection, commit in CORE_PROVENANCE.md | Daily source watch 07:41 UTC plus weekly core-integrity check |
| [degiro-connector](https://github.com/Chavithra/degiro-connector) | Runtime 3.0.36; exact wheel/tree/source in docs/connector-provenance.yaml | Daily PyPI releases and daily source watch; Renovate proposals require provenance review; audit |
| [Export-To-Ghostfolio](https://github.com/dickwolff/Export-To-Ghostfolio) | Contributor-only native CSV converter reference, pinned in tests/fixtures/degiro_v3_transition.yaml; Node image recorded there | Daily default-branch source watch; recorded Node image digest also has a daily Docker Hub metadata watch; regenerate after review |
| [Bitwarden CLI OSS](https://github.com/bitwarden/clients) | Separate runtime executable 2026.9.1 with both architecture SHA256 pins in Dockerfile; GPL/source notice in third_party/bitwarden | Daily dependency watch 07:29 UTC filters cli-v releases; native security/smoke checks |
| [Supercronic](https://github.com/aptible/supercronic) | Runtime scheduler version and architecture SHA256 pins in Dockerfile | Daily GitHub releases; full-image advisory scan |
| Python runtime and its complete closure | requirements.txt pins DEGIRO, PyOTP, requests, YAML, Apprise and every transitive package | Daily PyPI releases; weekly grouped Renovate proposals; pip-audit on PR/release/weekly checks; blocking image scan |
| Python developer/CI tools | requirements-dev.txt pins pip-audit and pytest | Daily dependency releases; weekly grouped Renovate proposals; complete CI environment audit |
| Python/Debian base image | Digest-pinned Python 3.12 slim in Dockerfile, OS packages inherited from it | Weekly Renovate proposals within Python 3.12; native image security checks |
| PostgreSQL/Redis contributor lab | Digest-pinned images in compose.lab.yaml | Weekly Renovate proposals require approval; lab isolated from production |
| GitHub Actions: checkout/setup-python, CodeQL, dependency-review, Trivy, Docker build/login, artifacts | Exact SHA in workflows | Weekly grouped Renovate proposals; reviewed CI and native scan gates |

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

Renovate security corrections bypass ordinary scheduling and release-age delays. The weekly
checks rerun vulnerability scans even without source changes. Supercronic's existing
Go-stdlib exception is constrained to the scheduler binary and accompanied by an
advisory scan; Bitwarden is covered by the blocking image scan. PRs and releases
still require the exact final-head CI and CodeRabbit evidence before integration.

## Dependency update ownership

Keep GitHub's dependency graph and Dependabot alerts enabled. Renovate consumes
those alerts and is the sole author of version and security-update PRs after the
handover below. Dependabot version PRs are disabled by zero limits in
`.github/dependabot.yml`; that does not disable its separate automatic security
updates. `scripts/configure_github.py` preserves this local security-update
setting instead of copying it from another repository.

`renovate.json` is the executable policy. Ordinary proposals run on Mondays in
UTC, with at most three open PRs and two new PRs per hour. Python releases wait
14 days; Actions and images wait three days. Missing release timestamps do not
bypass those delays. Python minor/patch changes share one group across runtime
and development requirements; action minor/patch/digest changes share another.
All installed Python versions stay exact, images retain digests and actions retain
commit SHAs. Interpreter proposals stay within Python 3.12. The repository's own
image is excluded; changing the public default image belongs to release work.

Major upgrades, every connector update and every Ghostfolio/PostgreSQL/Redis lab
update need Dependency Dashboard approval before ordinary branches are created.
Approval permits a proposal, not a merge or deployment. Connector adoption also
updates reviewed wheel/source provenance. Ghostfolio adoption must validate the
MANUAL profile identity change tracked in [issue #64](https://github.com/flowcool/ghostfolio-degiro-sync/issues/64),
with offline regressions and isolated native acceptance. PostgreSQL major
adoption must account for the existing lab volume and migration path.

Security PRs request the lowest fixed version immediately, without waiting for
the normal schedule, age, dashboard approval or ordinary PR limit. They still
need manual integration and all final-head checks. Renovate is not a Python
dependency solver: a security bump of a tightly coupled package can require a
companion pin update, such as Pydantic's exact `pydantic-core` requirement. Resolve
and verify the complete closure; never loosen pins to make a PR pass. Security
urgency does not waive connector provenance or lab compatibility validation.

The only enabled managers read requirements, Actions, Dockerfiles and Compose.
No custom manager changes Supercronic/Bitwarden versions independently of their
architecture checksums, and no manager regenerates the immutable core or changes
reference-converter fixtures. Their existing release/source watches remain in
place. Renovate and Dependabot do not replace `pip-audit`, image scans or API
compatibility tests. Automatic merge is disabled.

## Handover and rollback

1. Keep Dependabot automatic security updates enabled during onboarding. Verify
   dependency graph/alerts are enabled and the installed Renovate application has
   **Dependabot alerts: Read** permission for this repository. The application's
   declared permissions alone do not prove installation approval.
2. Validate Renovate configuration, run offline/core checks, and obtain completed
   CI and CodeRabbit coverage of the final head. `renovate.json` is explicitly
   included in CodeRabbit path filters. Merge through `scripts/merge_pr.py`.
3. Verify the first post-onboarding Renovate run successfully reads configuration
   and alerts. An empty alert list is valid; a failed or unauthorized read is not.
   Then disable **Dependabot security updates** in GitHub settings, leaving the
   graph and alerts enabled. The equivalent API is
   `DELETE /repos/{owner}/{repo}/automated-security-fixes`. Check the resulting
   repository `security_and_analysis.dependabot_security_updates.status` and that
   `GET /repos/{owner}/{repo}/vulnerability-alerts` still returns HTTP204.
4. Inspect any existing bot PRs before closing duplicates. Do not close a security
   correction without a verified replacement or adopted fix.

To roll back update ownership, first re-enable Dependabot automatic security
updates (`PUT` to the same endpoint), then pause Renovate for this repository and
revert the scoped source change through a reviewed PR. This restores the previous
version-update configuration. Reverting an implementation commit inside the
onboarding branch can leave the original default Renovate configuration in place;
the application must stay paused until ownership is explicit again. Preserve
alerts, journals and lab data. Neither handover nor rollback deploys services.

See the official [Dependabot options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)
and [Renovate options](https://docs.renovatebot.com/configuration-options/), including
[alert-based corrections](https://docs.renovatebot.com/configuration-options/#vulnerabilityalerts).
