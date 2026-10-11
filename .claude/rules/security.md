# Security rules — ghostfolio-degiro-sync

- Credentials (`DEGIRO_USERNAME`, `DEGIRO_PASSWORD`, `DEGIRO_TOTP_SECRET`, `GHOST_TOKEN`, `GHOST_ACCESS_TOKEN`): only from
  `os.environ`. Never hardcoded, never logged. The TOTP secret is a 2FA seed — treat it like a password.
- Secret storage: off-git SOPS store + pointer only (global ops rule). No secret in memory/KB/Beads.
- `degiro-connector` wraps DEGIRO's **private, reverse-engineered API** — endpoints can change without
  notice. Fail loud on unexpected shapes; keep the CSV backfill path as a recovery fallback.
- Any new external HTTP call or credential handling requires a recorded security review before merge:
  main-thread boundary checks and completed exact-final-head CodeRabbit review under the delegation policy.
- SSRF: retain DEGIRO's exact approved-origin allowlist before any credential-bearing request.
  Authentication, injection and recovery changes follow `docs/ghostfolio-auth.md`.
