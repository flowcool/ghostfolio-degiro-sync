# Read-only DEGIRO characterization

Offline pytest never loads real credentials. The operator procedure below logs
in once, discovers `intAccount`, reads raw transactions/account movements and
product/current-account data, then attempts logout. It does not contact Ghostfolio
or place/cancel orders. Redirects and unexpected endpoints are refused; requests
have connect/read timeouts and no automatic retries. HTTP405 is rejected before
the connector's unbounded maintenance HTML scraper.

The non-secret `secrets.pointer.yaml` locates the off-git SOPS store and loader.
The loader decrypts in memory and replaces itself with the requested process.
Never use `source`, command substitution, shell tracing or print decrypted output.

```sh
python3 /home/flow/claude_project/infra/rotation/run-degiro-env.py --check
python3 /home/flow/claude_project/infra/rotation/run-degiro-env.py \
  .venv/bin/python degiro_to_ghostfolio.py --read-only \
  --from-date 2026-10-01 --to-date 2026-10-08 --output tmp/reads/week.json
```

Snapshots are private financial input, mode0600, outside Git or under ignored
`tmp/`. Existing snapshots are never overwritten. Auth fields are excluded and raw
client/login responses are not stored. Store/loader access must remain restricted.
Use new filenames for each observation. A CSV statement can optionally be fetched
with explicit `--report-country nl --report-language en`; use the actual account
locale. CSV export and wide/split history comparisons are observations, not a proof
of unlimited history or server pagination completeness.

Window requests overlap one day. Equal stable identities are retained once;
conflicting duplicate identities fail. Multiple-window cash history requires
stable IDs; a one-window observation preserves unidentified cash rows so their
contract can be characterized. No identity is synthesized. Fractional quantities
and unmodeled cash fields are preserved. Unknown financial taxonomy and ambiguous
tax/FX relations remain gates before any activity mapping or financial writes.

If the read fails, stop and inspect the fixed failure stage using the Python
function boundary; do not enable connector DEBUG logs or print an auth exception.
Login/captcha/in-app approval/maintenance failures are not retried automatically.
There is no active cron at this phase. Rollback is a local code restore/revert;
the only remote mutation is the temporary authentication session, ended by logout.
