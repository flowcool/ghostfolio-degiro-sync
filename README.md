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
compensation, including zero-valued relevant interest rows, still block writes.

### Accounting policy: preserve cash yield and source identity

The adopted reporting policy retains zero Flatex interest as zero INTEREST
activities and represents positive monetary-fund compensation as INTEREST with
a distinct "DEGIRO money-market fund compensation" label and source identity.
This is a Ghostfolio reporting convention for cash yield, not a tax
classification or a claim that compensation is contractual bank interest.
It records earned cash without inflating external contributions or attributing
a dividend to an unidentified security.

The operator-provided explanation identifies compensation as an offset of
negative money-market fund yield. DEGIRO's official documents establish the
automatic cash investment and gradual move to bank cash accounts; they do not
specify compensation conditions. The decision combines that explanation with
the actual API/CSV credit and the verified native INTEREST representation.
No historical eligibility dates, thresholds or payout schedule are inferred.

Preserve each broker cash-event ID, timestamp, currency and credited amount.
Do not infer gross income, withholding or a product allocation from the credit.
Keep compensation and Flatex interest separately identifiable in reconciliation.
Negative amounts, corrections and reversals remain blocked until an exact
representation is established. Unobserved positive Flatex interest still needs
broker gross/net and tax evidence. Current cash is verified independently;
activity imports must not also increment account cash.

Florent delegated this arbitration on 2026-10-09. The decision removes the
need for further operator accounting choices; runtime support still requires
adapter identity/readback integration, offline and isolated acceptance, and
CSV/history reconciliation. Until those checks pass, the existing runtime blocks
remain active. The [accounting contract and native proof](docs/interest-compensation-policy.md)
record the representation, evidence and implementation requirements.
Production authorization remains separate.

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
