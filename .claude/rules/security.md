# Security rules — ghostfolio-degiro-sync

- Credentials (`DEGIRO_USERNAME`, `DEGIRO_PASSWORD`, `DEGIRO_TOTP_SECRET`, `GHOST_TOKEN`): only from
  `os.environ`. Never hardcoded, never logged. The TOTP secret is a 2FA seed — treat it like a password.
- Secret storage: off-git SOPS store + pointer only (global ops rule). No secret in memory/KB/Beads.
- `degiro-connector` wraps DEGIRO's **private, reverse-engineered API** — endpoints can change without
  notice. Fail loud on unexpected shapes; keep the CSV backfill path as a recovery fallback.
- Any new external HTTP call or credential handling → run `security-review` before merge.
- SSRF: keep an allow-list / prefix assertion on the Ghostfolio base URL (reuse IBKR `validate_ghost_host`).
