# Read-only broker capture

Use the Docker Compose setup from the root README. A read-only command authenticates to the configured vault, retrieves the DEGIRO login/TOTP secret, logs into the broker once, captures the requested data and attempts logout. It does not contact Ghostfolio or place/cancel orders.

```sh
docker compose run --rm degiro-sync --read-only \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD --output /state/capture.json
```

Replace dates and use a new filename every time. Optional `--report-country fr --report-language fr` requests a statement; select the actual account locale. Captures are financial data, written as private mode0600 files and never overwritten. Keep them outside Git.

The public command uses the pinned container image and environment configured through Compose. Never enable raw connector logging, print authentication responses or export the entire vault for troubleshooting. Capture success does not prove history completeness; unknown categories and ambiguous relationships still block financial synchronization.
