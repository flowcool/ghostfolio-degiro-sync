# Security rules — ghostfolio-degiro-sync

- Vault API credentials/master password and Ghostfolio tokens come from `os.environ`.
  Broker username/password/TOTP seed come only from the fresh exact vault item.
  Never hardcode, commit or log credentials, OTP, CLI session or authentication responses.
- `degiro-connector` wraps DEGIRO's **private, reverse-engineered API** — endpoints can change without
  notice. Fail loud on unexpected shapes; keep the CSV backfill path as a recovery fallback.
- Any new external HTTP call or credential handling requires a recorded security review before merge:
  main-thread boundary checks and completed exact-final-head CodeRabbit review under the PR template contract.
- SSRF: retain DEGIRO's exact approved-origin allowlist before any credential-bearing request.
  Authentication, injection and recovery changes follow `docs/ghostfolio-auth.md`.
