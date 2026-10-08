# ghostfolio-degiro-sync

Sync DEGIRO trades, dividends and cash into self-hosted [Ghostfolio](https://ghostfol.io), on a
schedule — sibling of [`ghostfolio-ibkr-sync`](../ghostfolio-ibkr-sync).

The adapter provides an explicit [read-only DEGIRO procedure](docs/read-only.md).
Normal sync still fails closed until the mapping and acceptance gates pass. Read the
approved [delivery plan](docs/plans/2026-10-08-degiro-sync.md) for implementation
and live-validation gates; [FINDINGS.md](FINDINGS.md) preserves the reconnaissance.

Foundation: [`degiro-connector`](https://github.com/Chavithra/degiro-connector) for the dated
activity feed (transactions + cash movements, unattended TOTP), with
[`Export-To-Ghostfolio`](https://github.com/dickwolff/Export-To-Ghostfolio) as CSV backfill/fallback.

The deliberate-copy architecture separates the broker adapter
(`degiro_to_ghostfolio.py`) from the immutable Ghostfolio core
(`ghostfolio_core.py`). [CORE_PROVENANCE.md](CORE_PROVENANCE.md) pins the canonical
IBKR source, lists its selected functions and documents human propagation.
CI fails on any core byte divergence and warns when IBKR main differs from the pin.
No shared package, automatic synchronization or IBKR repository modification is used.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_core.py --source ../ghostfolio-ibkr-sync --check-main
```

Tests are offline and HTTP is mocked. The local checker reads pinned Git objects
without modifying the sibling; the CI checker fetches into disposable state.
Credentials are supplied only from environment variables backed by an off-git
SOPS store and [non-secret pointer](secrets.pointer.yaml). Do not put real credentials into examples, tests or logs.

Current work and acceptance evidence live in Beads epic `infra-8tt.56` with
`project=ghostfolio-degiro-sync`, rather than a repository task-status list.
