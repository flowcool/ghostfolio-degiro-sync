<div align="center">

<img src="docs/assets/readme-banner.svg" alt="DEGIRO to Ghostfolio — portfolio sync on your infrastructure" width="880">

# DEGIRO → Ghostfolio

**Your broker activity. Your portfolio. Your infrastructure.**

Synchronize supported DEGIRO trades, dividends, fees and current EUR cash with your existing [Ghostfolio](https://ghostfol.io) account. Docker Compose includes the connector, Bitwarden CLI and scheduler; credentials come from Bitwarden or Vaultwarden.

[![Build and checks](https://github.com/flowcool/ghostfolio-degiro-sync/actions/workflows/checks.yml/badge.svg)](https://github.com/flowcool/ghostfolio-degiro-sync/actions/workflows/checks.yml)
[![Release](https://img.shields.io/github/v/release/flowcool/ghostfolio-degiro-sync)](https://github.com/flowcool/ghostfolio-degiro-sync/releases)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](compose.yaml)
[![License](https://img.shields.io/badge/License-MIT%20NON--AI-64748B)](LICENSE)

[**Compose**](#docker-compose) · [**Options**](#options-and-recommendations) · [**Simulation**](#review-a-simulation) · [**Troubleshooting**](#troubleshooting)

</div>

## What the tool does

Imports supported executions, paid dividends, characterized fees and cash yield into one existing Ghostfolio account, then sets independently verified current EUR cash. It preserves broker identities and durable write intent, blocks uncertain results, and offers a financial simulation before enabling writes.

## Prerequisites

The Python 3.14 image installs `ghostfolio_degiro_sync`, the pinned core and
its cash-rules resource. `python -m ghostfolio_degiro_sync` accepts the same
options as the transitional script command. Both work from any directory in
the image. Compose continues to select the command and schedule automatically.

- Docker Compose v2, an existing Ghostfolio instance and a Docker network reaching it.
- A DEGIRO account using **TOTP** and a Bitwarden or Vaultwarden Login item containing its username, password and TOTP seed. App confirmation (`in_app_required`) and captcha (`captcha_required`) are unsupported.
- Vault API credentials, exactly one Ghostfolio credential, and explicitly selected source and destination accounts.
- An instrument mapping and a private persistent journal directory; prepare the mounts below before starting.

## Limits

- Quote currencies: **EUR, USD and JPY only**. Current cash: **EUR only**.
- Cash-statement relationships are characterized for **French (`fr`) statements**; other statement languages are not verified.
- Normal Compose operation reads a **rolling 90-day window** through the Europe/Zurich date. It reconstructs neither complete history nor historical cost basis.
- Existing activities are never automatically corrected or deleted. Unknown or ambiguous relevant evidence blocks synchronization.

**Unofficial API:** this project is not affiliated with DEGIRO. Its reverse-engineered API can change without notice. Automated access may conflict with DEGIRO's terms of use and carries an account-blocking risk. Assess that risk before using the connector.

## Docker Compose

Paste this into a Portainer stack or save it as `compose.yaml`. Supply the variables through Portainer's stack environment or a local `.env` ([template](.env.example)). No clone or local build is needed; the published image supports amd64 and arm64.

```yaml
# Existing Ghostfolio network; run once by default, CRON is opt-in.
services:
  degiro-sync:
    image: ${DEGIRO_IMAGE:-ghcr.io/flowcool/ghostfolio-degiro-sync:v0.4.1}
    restart: ${RESTART_POLICY:-no}
    user: "10001:10001"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs: ["/tmp:rw,nosuid,nodev,size=32m"]
    environment:
      BW_SERVER: ${BW_SERVER:-https://vault.bitwarden.com}
      BW_CLIENTID: ${BW_CLIENTID:-}
      BW_CLIENTSECRET: ${BW_CLIENTSECRET:-}
      BW_PASSWORD: ${BW_PASSWORD:-}
      BW_ITEM_ID: ${BW_ITEM_ID:-}
      GHOST_TOKEN: ${GHOST_TOKEN:-}
      GHOST_ACCESS_TOKEN: ${GHOST_ACCESS_TOKEN:-}
      GHOST_HOST: ${GHOST_HOST:-http://ghostfolio:3333}
      DEGIRO_ACCOUNT_ID: ${DEGIRO_ACCOUNT_ID:?Set source account}
      GHOST_ACCOUNT_ID: ${GHOST_ACCOUNT_ID:?Set target account}
      MAPPING_FILE: /config/mapping.yaml
      STATE_DIR: /state
      SYNC_MODE: rolling
      LOOKBACK_DAYS: "90"
      DRY_RUN: ${DRY_RUN:-1}
      TZ: Europe/Zurich
      CRON: ${CRON:-}
      APPRISE_URLS: ${APPRISE_URLS:-}
      APPRISE_TIMEOUT: ${APPRISE_TIMEOUT:-10}
    volumes:
      - type: bind
        source: ${DEGIRO_MAPPING_PATH:-./mapping.yaml}
        target: /config/mapping.yaml
        read_only: true
        bind: {create_host_path: false}
      - type: bind
        source: ${DEGIRO_STATE_PATH:-./state}
        target: /state
        bind: {create_host_path: false}
    networks: [ghostfolio]
networks:
  ghostfolio:
    external: true
    name: ${GHOST_NETWORK:?Set existing Ghostfolio network}
```

Start with `DRY_RUN=1` and an empty `CRON`. In Portainer, use absolute host paths for both mounts.

## Options and recommendations

| Option | Role | Default | Recommendation |
| --- | --- | --- | --- |
| `BW_SERVER` | Vault HTTPS origin | `https://vault.bitwarden.com` | Use your final origin without a trailing slash; EU cloud: `https://vault.bitwarden.eu` |
| `BW_CLIENTID` | Personal Bitwarden API-key client ID | Required | Use a dedicated vault account containing only the needed item |
| `BW_CLIENTSECRET` | Personal API-key secret | Required | Obtain with the client ID from **Security → Keys → API key** |
| `BW_PASSWORD` | Vault master password | Required | Needed to unlock the encrypted vault |
| `BW_ITEM_ID` | DEGIRO Login item UUID | Required | Exact UUID, not the display name |
| `GHOST_HOST` | Ghostfolio origin | `http://ghostfolio:3333` | Prefer the existing Docker hostname on the shared network; no trailing slash |
| `GHOST_ACCESS_TOKEN` | Ghostfolio Security Token | One credential required | Recommended: exchanged for a fresh bearer on every execution |
| `GHOST_TOKEN` | Legacy expiring bearer | Unset | Alternative only; configure exactly one Ghostfolio credential |
| `DEGIRO_ACCOUNT_ID` | Numeric source `intAccount` | Required | Discover below if unknown |
| `GHOST_ACCOUNT_ID` | Destination account UUID | Required | Select the intended EUR account; discover below if unknown |
| `GHOST_NETWORK` | Existing Docker network | Required | Must reach the configured Ghostfolio hostname |
| `DEGIRO_MAPPING_PATH` | Host mapping file | `./mapping.yaml` | Verify every ISIN, Yahoo ticker and quote currency; readable by UID 10001 |
| `DEGIRO_STATE_PATH` | Persistent journal directory | `./state` | Owned by UID/GID 10001, mode 0700; include in backups |
| `DRY_RUN` | Financial simulation | `1` | Keep enabled until proposals are reviewed; `0` permits financial writes |
| `CRON` | Schedule | Empty: run once | After a manual simulation, `'15 6 * * *'` runs daily at 06:15 |
| `RESTART_POLICY` | Docker restart policy | `no` | With `CRON`, set `unless-stopped` to restart the scheduler after a crash or host reboot |
| `APPRISE_URLS` | Failure alerts | Empty: disabled | Recommended for scheduled runs; JSON list, e.g. `'["ntfy://notification-host/topic"]'` |
| `APPRISE_TIMEOUT` | Alert deadline | `10` seconds | Keep the default; allowed range 1–30 |
| `DEGIRO_IMAGE` | Published image tag or digest | `ghcr.io/flowcool/ghostfolio-degiro-sync:v0.4.1` | Follow a reviewed release, pin an immutable digest for controlled upgrades, or explicitly choose `:latest` |

**BREAKING:** a valid IANA `TZ` is required for financial writes. Missing or invalid `TZ` forces simulation and emits a fixed warning. Absent or blank `DRY_RUN` also simulates and emits `DRY_RUN not set: simulation, nothing written`. Values are trimmed and case-insensitive: `1`/`true`/`yes`/`on` simulate; `0`/`false`/`no`/`off` request writes. Any other value stops before broker or Ghostfolio access.

Compose fixes `SYNC_MODE=rolling`, `LOOKBACK_DAYS=90`, `TZ=Europe/Zurich`, `/config/mapping.yaml` and `/state`. Both cron and the broker date boundary use Europe/Zurich. The container runs as UID/GID 10001 with a read-only root filesystem and no Linux capabilities.

Synchronization requires an explicit `SYNC_MODE`; absent or blank values fail at configuration before credential loading. The supported Compose definition already supplies `rolling`. Advanced contributor invocations must explicitly select `rolling`, `prospective` or `full_history`; selecting a mode does not bypass its evidence requirements.

Use single quotes around secrets in `.env` to preserve literal `$` and `#`. Restrict access to this file, the Docker host and backups. Environment changes require recreating the container.

## Vault and mapping

The vault item must be a **Login** containing the DEGIRO username, password and **TOTP secret**, not a temporary code. Supported TOTP uses SHA1, six digits and a 30-second interval, with a Base32 seed or `otpauth://totp/...` URI. Every broker execution opens an isolated vault session; failure blocks login. Remove direct `DEGIRO_USERNAME`, `DEGIRO_PASSWORD` and `DEGIRO_TOTP_SECRET` variables: they are rejected even when empty.

Create `mapping.yaml` from [mapping.yaml.example](mapping.yaml.example), with an entry for every instrument:

```yaml
US0378331005:
  symbol: AAPL
  currency: USD
```

Keys must be valid ISINs; entries contain exactly `symbol` and `currency`, without surrounding whitespace. Quote currencies are **EUR, USD and JPY** only. Conflicting currencies for the same symbol reject the mapping. Current cash supports EUR only.

Prepare the mounts, using your configured host paths if different:

```sh
mkdir -p state
chmod 600 mapping.yaml
sudo chown 10001:10001 mapping.yaml state
sudo chmod 700 state
# If using a local .env:
chmod 600 .env
```

Both mounts must already exist; Compose refuses to create missing paths silently. On NAS hosts, also check bind-mount ACLs.

## Discover account IDs

Skip this if both IDs are known. Use nonempty placeholders for unknown IDs in the Compose environment. For DEGIRO, replace the dates with a recent interval, then read `source_account` from the private capture:

```sh
docker compose run --rm degiro-sync --read-only \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --output /state/account-discovery.json
```

For Ghostfolio, read the account ID, name and currency from this private output:

```sh
docker compose run --rm degiro-sync --ghost-accounts --output /state/ghostfolio-accounts.json
```

Set both real IDs before synchronizing. Discovery performs authentication and reads only: the first command contacts the vault and DEGIRO, the second contacts Ghostfolio. Private outputs are never overwritten; use a new name when repeating a capture.

## Review a simulation

With `DRY_RUN=1` and an empty `CRON`:

```sh
docker compose run --rm degiro-sync --sync
```

Docker output shows each proposed activity, the cash change and exclusion counts. Example with synthetic values:

```text
INFO: Sync DRY_RUN: 1 proposed activities, 0 accepted
INFO: [DRY RUN] "2026-10-09T00:00:00Z" "DIVIDEND" "TEST" qty=1 price=12.5 USD fee=1.8
INFO: [DRY RUN] Ghostfolio cash: EUR 30.00 -> 42.50 (no update sent)
INFO: [DRY RUN] Candidate exclusions: already_imported=2 manual_match=1 duplicate_candidate=1
INFO: Rolling 90-day contract verified; historical completeness and basis remain unverified
```

Review dates, tickers, quantities, prices, fees and cash against DEGIRO and Ghostfolio. `already_imported` counts unchanged canonical activities, `manual_match` matching manual entries, and `duplicate_candidate` repeated normalized candidates. Counts cover activity candidates, not every broker cash row. Zero accepted is expected: no financial write is sent. Logs contain financial details; keep them private.

No report is created automatically. Optionally add `--plan-output /state/first-plan.json` for the exact proposal, period, cash before/after and exclusion counts in a private JSON file (mode 0600, no overwrites).

Unknown events, ambiguous matches, mismatched holdings, incomplete statements or uncertain imports block synchronization. Rolling mode verifies the last 90 days, not earlier history or cost basis. Older holdings and corporate actions need separate reconciliation. Cash relationships are characterized for French statements and EUR cash; the unofficial broker API is not a universal history importer. See [synchronization contracts](docs/synchronization.md) and the [cash-yield accounting policy](docs/interest-compensation-policy.md).

## Scheduled runs and alerts

Set `CRON='15 6 * * *'`, `RESTART_POLICY=unless-stopped`, and keep `DRY_RUN=1` for daily simulations:

```sh
docker compose up -d
docker compose logs --tail 100 -f
```

Keep the default `RESTART_POLICY=no` for run-once operation. With a nonempty `CRON`, set `RESTART_POLICY=unless-stopped` so Docker restarts the scheduler after a crash or host reboot, unless you explicitly stopped it. Leaving the default in scheduled mode can silently stop future runs: the failed-run alert cannot execute when the scheduler is absent. A restart policy does not detect missed runs or guarantee scheduler health.

Scheduling waits for the first cron tick. The optional [dry-run overlay](compose.dry-run.yaml) fixes both simulation and this schedule. Stop the scheduler before a manual run against the same account state.

Images published from `v0.4.0` include a local healthcheck. The probe verifies that scheduled PID 1 is Supercronic in a running or sleeping state; it detects a stopped process without network or credential access. Docker marks repeated failures `unhealthy`; an exited container already has an exited status. Run-once mode bypasses the probe. Health status does not prove a job ran, detect missed ticks or deliver an alert. Docker restart policies respond to process exit, not `unhealthy`; external monitoring is needed for alerts or successful-run silence detection. A manual command overriding a scheduled container's entrypoint is not a scheduler and may be marked unhealthy if it lasts beyond the probe grace period.

After reviewing a successful simulation and verifying your Ghostfolio backup, set `DRY_RUN=0` and recreate the service to enable imports and cash updates. Existing activities are not automatically corrected or deleted. Preserve state: removing the journal cannot resolve an uncertain import, and image rollback cannot undo financial changes.

Apprise sends one sanitized alert for each failed invocation, including manual and scheduled simulations. Successful simulations are silent. An explicit live request forced into simulation by missing or invalid `TZ` sends one summary. A failure takes precedence over that summary. No separate Apprise server is required; configure destinations through `APPRISE_URLS`. See [notifications](docs/notifications.md) and [recovery](docs/recovery.md).

## Troubleshooting

Failures return exit code 1 and a stable `stage=... reason=...` diagnostic. Invalid CLI arguments return 2. Diagnostics exclude credentials, raw responses and private exception text.

| Stage | Check |
| --- | --- |
| `config` | Required values, exactly one Ghostfolio credential, mapping, account IDs and mount permissions |
| `vault` / `login` | Personal API key, master password, item UUID and supported TOTP secret |
| `login` / `in_app_required` | DEGIRO requires app confirmation; this flow is unsupported. Use an account configured for supported TOTP |
| `login` / `captcha_required` | DEGIRO requires a captcha; automated solving is unsupported. Resolve the broker challenge separately before retrying |
| Broker read stages | Broker availability and response compatibility; a generic failure does not prove missing history |
| `ghostfolio` | Reachable final origin, Docker network, credential and destination account |
| `sync` | Statement/holdings reconciliation, rolling coverage and unresolved write intent |
| `output` | New writable private capture/proposal path |

Keep DRY_RUN enabled while resolving failures. Details: [read-only captures](docs/read-only.md), [authentication](docs/ghostfolio-auth.md), [recovery](docs/recovery.md). [Report an issue](https://github.com/flowcool/ghostfolio-degiro-sync/issues) with image version, options, exit code and sanitized diagnostic; redact financial proposal lines and keep credentials and captures private.

## Development and compatibility

[Documentation index](docs/README.md) separates user contracts from contributor material. [CONTRIBUTING.md](CONTRIBUTING.md) covers offline tests and contributor builds. See [architecture](docs/architecture.md) for module contracts and [upstreams](docs/upstreams.md) for compatibility monitoring. Host Python is a developer workflow. Release notices do not deploy or establish compatibility automatically.

The connector reads both legacy DEGIRO comments and generation-1 comments
(`DEGIRO#v1#<source-account>:<kind>:<source-id>`). Both forms identify the same
source event. Conflicting or duplicate ownership stops the account. Ownership is
checked across the complete destination, so changing the target account cannot
make an old event new. Normal synchronization does not move or rewrite history.
Source lifetime identity and target-image compatibility require separate
qualification; see the [source contract](docs/source-contract.md).

New imports write generation 1. Historical comments remain unchanged until an
explicit, qualified maintenance operation. After any v1 rows exist, safe halt uses
the exact qualified candidate digest with `DRY_RUN=1` and the existing Compose
target. If that candidate cannot start, leave writers stopped for a compatible
repair. A Git revert or comment reversal alone does not qualify an older binary.
Candidate lab proof and historical conversion require their own authorization.

Simulation reconciliation compares source events with owned destination rows before
import deduplication. It uses the original JSON decimals when both read phases
provide them. Missing wire evidence, ownership contention or unsupported units
remain uncertain; no amount threshold hides a difference. Dividend activity
quantity `1` does not prove a security quantity. The report adds no reads or
writes and does not change import selection, exit status or notifications. Private
captures may retain original financial JSON for this comparison; protect them as
financial data. They are not source lifetime-coverage proof.
