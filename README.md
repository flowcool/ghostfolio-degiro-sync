# ghostfolio-degiro-sync

Sync DEGIRO trades, dividends and cash into self-hosted [Ghostfolio](https://ghostfol.io), on a
schedule — sibling of [`ghostfolio-ibkr-sync`](https://github.com/flowcool/ghostfolio-ibkr-sync).

The adapter provides an explicit [read-only DEGIRO procedure](docs/read-only.md).
An explicit [DRY_RUN synchronization command](docs/synchronization.md) now
reconciles configured source/target identities and mappings. Live sync fails
closed until the history and acceptance gates pass. Read the
approved [delivery plan](docs/plans/2026-10-08-degiro-sync.md) for implementation
and live-validation gates; [FINDINGS.md](FINDINGS.md) preserves the reconnaissance.

Foundation: [`degiro-connector`](https://github.com/Chavithra/degiro-connector) for the dated
activity feed (transactions + cash movements, unattended TOTP), with
[`Export-To-Ghostfolio`](https://github.com/dickwolff/Export-To-Ghostfolio) as CSV backfill/fallback.

## Operational readiness

The guarded adapter implements executed BUY/SELL, paid DIVIDEND with verified
withholding, autonomous exchange-connection FEE and verified current cash.
DRY_RUN is the default. An unknown or ambiguous relevant event blocks the account
before financial dispatch.

Known incompatible API formats produce explicit privacy-safe errors before
synchronization or successful read-only snapshot publication; detection uses
response structure and content rather than a calendar cutoff. See the
[source contract](docs/source-contract.md) for supported shapes and diagnostics.
Legacy monetary-fund formats remain unsupported. Flatex interest and monetary-fund
compensation, including zero-valued relevant interest rows, still block writes;
the [accounting-policy document](docs/interest-compensation-policy.md) is a proposal
and does not enable their import.

The disposable native Ghostfolio lab proves exact import/readback, repeat imports,
mapping stability and conservative uncertain-result recovery. Real historical
completeness and CSV adoption remain unverified: matching old output does not
prove omitted events, instrument identity, equivalent fees or timestamps. No
successful whole-account real synchronization or production readiness is claimed.
Production financial writes, cleanup and deployment require separate approval.
Source prereleases describe delivered code and evidence; they do not publish a
container or satisfy those acceptance gates.

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

The [runtime guide](docs/runtime.md) documents native amd64/arm64 validation,
rootless run-once/cron, connector source parity and safe secret injection.
Container checks build and smoke only; they do not publish or deploy an image.
The [recovery guide](docs/recovery.md) explains durable intent and explicit
positive readback; the [isolated acceptance report](docs/isolated-acceptance.md)
documents native delayed-result evidence, conservative CSV overlap and the
offline exact-ID cleanup preflight. Production writes retain separate approval.
The [read-only reconciliation report](docs/readonly-reconciliation.md) records
actual destination/V3 output matches and the deliberately retained source gates.

Current work and acceptance evidence live in Beads epic `infra-8tt.56` with
`project=ghostfolio-degiro-sync`, rather than a repository task-status list.
