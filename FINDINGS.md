# FINDINGS — ghostfolio-degiro-sync (reconnaissance)

**Status:** Reconnaissance only. No code written. No Beads epic yet. This document is the
handoff for the next agent. Date: 2026-10-08. Author: Claude (Opus 4.8) session.

**One-line verdict:** DEGIRO → Ghostfolio is **feasible as an unattended cron**, same design as
`ghostfolio-ibkr-sync`. The only genuinely new part is the broker adapter (data fetch). The
Ghostfolio-side core of the IBKR repo is reusable.

---

## 1. Foundation: `Chavithra/degiro-connector` (verified by reading the source)

- Repo: https://github.com/Chavithra/degiro-connector — Python, PyPI package `degiro-connector`.
- License: permissive. Clone tip inspected was dated **2026-05-26** (`--depth 1`, so = default-branch
  head at clone time). Still live: `degiro-mcp` (PyPI, published Oct 2026) depends on it.
- DEGIRO has **no official public API** — this library wraps DEGIRO's private/reverse-engineered
  endpoints. **Breakage risk is structural** (endpoints can change without notice). Mitigation = the
  CSV backfill path below as a fallback.

### Why it beats the raw-HTTP approach (and beats picsou — see §4)

It exposes a **full dated-activity feed**, not just positions. Verified actions present in
`src/degiro_connector/trading/actions/`:

| File | Gives |
|---|---|
| `action_get_transactions_history.py` | dated buys/sells |
| `action_get_orders_history.py` | order history |
| `action_get_account_overview.py` | **cash movements** (dividends, fees, taxes) |
| `action_get_account_report.py` | cash report export (CSV/HTML/PDF/XLS) |
| `action_get_upcoming_payments.py`, `action_get_position_report.py` | payments, positions |

This maps 1:1 onto what the IBKR Flex Query gives (`parse_trades` + `parse_cash_dividends` +
`parse_cash_report`).

### Unattended auth confirmed (the key capability picsou lacks)

`action_connect.py:34-67` — the `Credentials` model accepts `totp_secret_key`; when present the library
generates the OTP itself via `pyotp.TOTP(totp_secret_key).now()`. So **no interactive 2FA** → cron works.
Login error handling is explicit: status 6 = "provide totp_secret", status 12 = in-app approval required,
captcha → `CaptchaRequiredError`. In-app token path also supported.

---

## 2. Backfill / fallback: `dickwolff/Export-To-Ghostfolio` (verified)

- Repo: https://github.com/dickwolff/Export-To-Ghostfolio — TypeScript, Apache-2.0, very active.
- Has mature DEGIRO converters: `degiroConverter.ts`, **`degiroConverterV2.ts`, `degiroConverterV3.ts`**
  (with tests). Converts the DEGIRO CSV export (Activity → Account statement) → Ghostfolio JSON, with
  ISIN→Yahoo resolution.
- Use it for (a) initial historical backfill and (b) a secondary recovery path if the private API breaks.
  It is a different stack (TS), so treat it as a tool, not a code source to merge.

---

## 3. What to reuse from `../ghostfolio-ibkr-sync` (concrete, with references)

The IBKR repo is a **mono-file** (`ibkr_to_ghostfolio.py`, ~1480 lines) but has clean function
boundaries. Two layers:

**REUSE AS-IS (Ghostfolio core, broker-agnostic, ~60% of the repo):**
- `ghost_headers`, `ghost_exchange_access_token`, `ghost_get_accounts`, `ghost_find_account_id`,
  `ghost_get_existing_orders`, `ghost_import_activities`, `ghost_update_cash_balance`,
  `accepted_import_subset`, `parse_unresolved_symbol`, `mark_import_uncertain`
- `load_mapping` / `resolve_symbol` (ISIN→Yahoo + overrides), `mapping.yaml.example`
- `convert_trade_to_activity` / `convert_dividend_to_activity` (the activity shape + dedup comment key)
- `filter_trades_by_holdings` (the holdings gate), `activity_is_active`, `activity_date_is_current`
- `minor_unit_conversion` / GBX-pence handling, `DRY_RUN` flow, `validate_ghost_host` (SSRF guard)
- `cleanup_duplicates.py`, `cleanup_dividends.py`, `cleanup_recovery.py`
- Runtime harness: `Dockerfile` (python:3.12-slim + supercronic cron, pinned SHA), `entrypoint.sh`
  (CRON vs run-once), `requirements.txt` pinning style, `tests/` offline pattern, `.github/` CI.

**REPLACE (broker layer):**
- `fetch_flex_report` + `parse_trades` / `parse_cash_report` / `parse_cash_dividends`
  → a DEGIRO adapter built on `degiro-connector` (transactions_history + account_overview →
  internal activity list).

**Decision left to the next agent** (Florent's framing): whether to (a) copy the IBKR core into this
repo as a mono-file and swap the broker layer, or (b) first extract a shared `ghostfolio-sync-core`
module consumed by both repos. (a) is faster and matches the existing "mono-file by design" convention;
(b) is cleaner long-term but is a refactor of a working production repo — do not start it without
explicit scope approval. **Recommendation: start with (a)**, extract later if BourseDirect confirms a
third consumer.

**Dependency delta vs IBKR:** add `degiro-connector` + `pyotp` (transitively pulled). IBKR core is
`requests`+`pyyaml` only; keep that minimalism for the Ghostfolio side.

---

## 4. Do NOT use picsou `degiro-auth` as a data source (verified why)

`Cloeille/picsou-finance` `services/degiro-auth/main.py` (read in full):
- Does **not** use `degiro-connector`; it re-implements the private DEGIRO HTTP API in `httpx`.
- Fetches **only** `/trading/secure/v5/update` with `portfolio`+`cashFunds` → **positions + cash
  snapshot. No transactions, no dividends.** Useless as a Ghostfolio activity feed.
- **Never stores the TOTP secret** — interactive 2FA every time, explicit ADR
  `docs/decisions/2026-08-05-degiro-session-only-no-stored-totp.md`. Session ~30 min, no refresh. **Not
  cron-able.**
- License: Apache-2.0 **+ additional restrictions** (non-commercial). Reference only; do not copy code.

Value of picsou here: a worked reference of the live DEGIRO login/portfolio endpoint shapes and quirks
(`FLATEX_EUR` cash pseudo-position, literal `"NULL"` product fields) — useful if `degiro-connector`
breaks and the adapter must be hand-patched.

---

## 5. Open questions / gates (resolve before writing the plan)

1. **TOTP secret available? — RESOLVED (Florent, 2026-10-08): YES, available.** Unattended cron is
   therefore viable. Store it per the global secrets rule (off-git SOPS + pointer), `DEGIRO_TOTP_SECRET`
   from `os.environ` only.
2. **`account_overview` data model** — confirm it distinguishes dividend vs fee vs tax vs FX, to map
   cleanly onto Ghostfolio DIVIDEND/FEE activities. Not yet read in detail (only the endpoint existence
   is confirmed). Read `action_get_account_overview.py` + its response model before coding the mapping.
3. **Transaction-history date window** — confirm max look-back and paging, to size the ongoing-sync vs
   backfill split (IBKR Flex is 365 days; DEGIRO likely different).
4. **Credentials storage** — follow the global secrets rule: no secret in memory/KB/Beads; off-git SOPS
   store + pointer. `DEGIRO_USERNAME`/`DEGIRO_PASSWORD`/`DEGIRO_TOTP_SECRET` from `os.environ` only.

---

## 6. Next agent — suggested first steps

1. Confirm the §5 gates with Florent (esp. TOTP secret).
2. Scope + plan (plan-quality rules apply: RTFM `degiro-connector` fully, no implementation-intuition).
3. Create the Beads epic (sibling of or child under ghostfolio epic `infra-8tt`; metadata
   `project=ghostfolio-degiro-sync`) and atomic issues.
4. `git init` + first atomic commit of the scaffold once scope is agreed.

## References

- degiro-connector: https://github.com/Chavithra/degiro-connector
- Export-To-Ghostfolio: https://github.com/dickwolff/Export-To-Ghostfolio
- picsou-finance (reference only): https://github.com/Cloeille/picsou-finance
- IBKR sibling repo: `../ghostfolio-ibkr-sync` (see its `CLAUDE.md` for Ghostfolio API traps)
- Ghostfolio API traps KB: `knowledge-base/bundle/operations/ghostfolio/api-traps.md`
