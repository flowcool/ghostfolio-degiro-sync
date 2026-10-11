# Compose definitions

The root [README](../README.md) is the complete supported deployment guide.

- `compose.yaml`: one importer for one DEGIRO/Ghostfolio account pair, local image build, existing Ghostfolio network, private mapping and persistent journal. Default is run-once DRY_RUN.
- `compose.dry-run.yaml`: optional overlay fixing simulation mode and a daily 06:15 Europe/Zurich schedule.
- `compose.lab.yaml`: contributor-only synthetic Ghostfolio lab, isolated from production; see CONTRIBUTING.md. It is not a user deployment prerequisite.

Vault and Ghostfolio credentials can be supplied in the ignored local `.env` or injected environment. No configuration backend is imposed. Never publish `docker compose config` output from a real deployment because it contains rendered credentials.

A running service keeps its original environment until recreated. Vault item contents are fetched afresh on each execution. Stop the scheduler before manual catch-up or recovery and retain the existing journal. The simulation overlay cannot activate writes; start the base alone only after reviewing the account and configuring DRY_RUN=0.

## Configuration contract

Required vault values: `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_PASSWORD`, `BW_ITEM_ID`;
`BW_SERVER` defaults to the US Bitwarden HTTPS origin. The item UUID selects one
Login with username, password and TOTP seed, fetched fresh at every broker run.

Ghostfolio uses `GHOST_HOST` (default container origin) and exactly one of
`GHOST_ACCESS_TOKEN` (recommended Security Token) or `GHOST_TOKEN` (legacy bearer).
`DEGIRO_ACCOUNT_ID`, `GHOST_ACCOUNT_ID` and `GHOST_NETWORK` select the account pair
and existing reachable Docker network. Credentials are verbatim environment values.

`DEGIRO_MAPPING_PATH` defaults to `./mapping.yaml`, mounted read-only and readable
by UID10001. `DEGIRO_STATE_PATH` defaults to `./state`, writable by UID/GID10001,
mode0700. `.env` and mapping are private mode0600. Missing bind paths are refused.
`DRY_RUN=1` and empty `CRON` are safe defaults; APPRISE_URLS is optional.

The container accepts `--read-only --from-date DATE --to-date DATE --output PATH`
for private broker discovery and `--ghost-accounts --output PATH` for private
Ghostfolio ID/name/currency discovery. The latter never contacts the broker.
Use a nonempty placeholder for unknown IDs during discovery, then replace it.
`--sync --plan-output /state/plan.json` requires DRY_RUN and publishes exact proposed
activities/cash without credentials. Outputs are mode0600 and existing destinations
are refused before authentication; choose new filenames and keep captures private.
