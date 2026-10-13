# Compose definitions

The root [README](../README.md) is the complete supported deployment guide.

- `compose.yaml`: one importer for one DEGIRO/Ghostfolio account pair, published GHCR image, existing Ghostfolio network, private mapping and persistent journal. Default is run-once DRY_RUN.
- `compose.build.yaml`: contributor-only local image build overlay.
- `compose.dry-run.yaml`: optional overlay fixing simulation mode and a daily 06:15 Europe/Zurich schedule.

Vault and Ghostfolio credentials can be supplied in the ignored local `.env` or injected environment. No configuration backend is imposed. Never publish `docker compose config` output from a real deployment because it contains rendered credentials.

A running service keeps its original environment until recreated. Vault item contents are fetched afresh on each execution. Stop the scheduler before manual catch-up or recovery and retain the existing journal. The simulation overlay cannot activate writes; start the base alone only after reviewing the account and configuring DRY_RUN=0.

## Configuration reference

Use the [README options](../README.md#options-and-recommendations),
[mapping and mounts](../README.md#vault-and-mapping),
[account discovery](../README.md#discover-account-ids) and
[scheduler restart guidance](../README.md#scheduled-runs-and-alerts).
Keep discovery outputs and proposals private and choose a new filename for each
capture; existing output paths are refused before authentication.
