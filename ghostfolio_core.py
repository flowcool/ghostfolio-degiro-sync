import json


import logging


import re


from collections.abc import Mapping


from datetime import UTC, datetime


from math import isfinite


from typing import Any


import requests


log = logging.getLogger(__name__)


Config = dict[str, Any]


GHOST_REDIRECT_ERROR = "Ghostfolio request redirected"


_UNRESOLVED_SYMBOL_RE = re.compile(
    r'symbol \(\\?"([^"\\]+)\\?"\) cannot be resolved by the data source')


def ghost_headers(token: str | None) -> dict[str, str]:
    """Return common headers for Ghostfolio API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def ghost_response_is_redirect(resp: requests.Response) -> bool:
    """Return whether a Ghostfolio response is a redirect."""
    return 300 <= resp.status_code < 400


def activity_date_is_current(activity: Mapping[str, Any]) -> bool:
    """Conservatively refuse future instants (server drafts use local end of day)."""
    try:
        instant = datetime.fromisoformat(activity["date"].replace("Z", "+00:00"))
        return instant.tzinfo is not None and instant <= datetime.now(UTC)
    except (KeyError, TypeError, AttributeError, ValueError):
        return False


def activity_is_active(activity: Any) -> bool:
    """Follow Ghostfolio draft/exclusion tags; refuse malformed active context."""
    if not isinstance(activity, dict):
        raise RuntimeError("Invalid activity eligibility context")
    account = activity.get("account")
    if account is None:
        account = {}
    if not isinstance(account, dict):
        raise RuntimeError("Invalid account eligibility context")
    for context in (activity, account):
        for flag in ("isDraft", "isExcluded"):
            if flag in context and not isinstance(context[flag], bool):
                raise RuntimeError("Invalid activity eligibility flag")
        tags = context.get("tags", [])
        if (not isinstance(tags, list)
                or any(not isinstance(tag, dict) or not isinstance(tag.get("id"), str)
                       or not tag["id"].strip() for tag in tags)):
            raise RuntimeError("Invalid activity eligibility tags")
    inactive_tags = {"0c077abd-eca2-4cbb-818c-6cefbf2d169a",
                     "f2e868af-8333-459f-b161-cbc6544c24bd"}
    return not (activity.get("isDraft") or activity.get("isExcluded")
                or account.get("isDraft") or account.get("isExcluded")
                or any(tag["id"] in inactive_tags
                       for context in (activity, account) for tag in context.get("tags", [])))


def ghost_get_accounts(config: Config) -> Any:
    """Fetch all accounts from Ghostfolio."""
    url = f"{config['ghost_host']}/api/v1/account"
    resp = requests.get(url, headers=ghost_headers(config["ghost_token"]), timeout=120,
                        allow_redirects=False)
    if ghost_response_is_redirect(resp):
        raise RuntimeError(GHOST_REDIRECT_ERROR)
    resp.raise_for_status()
    return resp.json()


def ghost_find_account_id(config: Config, account_name: str) -> str | None:
    """Find a Ghostfolio account ID by name.

    Returns None if no account matches, so the caller can skip this account and
    still process the remaining ones.
    """
    data = ghost_get_accounts(config)
    accounts = data.get("accounts", data) if isinstance(data, dict) else data
    for acc in accounts:
        if acc.get("name") == account_name:
            if not activity_is_active({"account": acc}):
                raise RuntimeError("Ghostfolio target account is excluded; refusing sync")
            account_id: str = acc["id"]
            return account_id
    log.error("Ghostfolio account '%s' not found. Available: %s",
              account_name, [a["name"] for a in accounts])
    return None


def parse_unresolved_symbol(body: Any, text: str = "") -> str | None:
    """Return the ticker Ghostfolio could not resolve from an import 400, else None.

    None means the 400 is not a per-symbol resolution error (too many
    activities, premium required, invalid data source, ...) and must not be
    retried.  body is the parsed JSON (dict or None); text is the raw fallback.
    """
    messages = []
    if isinstance(body, dict):
        msg = body.get("message")
        if isinstance(msg, list):
            messages = [str(x) for x in msg]
        elif msg:
            messages = [str(msg)]
    haystack = " ".join(messages) if messages else (text or "")
    match = _UNRESOLVED_SYMBOL_RE.search(haystack)
    return match.group(1) if match else None


def accepted_import_subset(
    submitted: list[dict[str, Any]], body: Any,
) -> list[dict[str, Any]]:
    """Map server-created rows to unique submitted identities, never sent counts."""
    if not isinstance(body, dict) or not isinstance(body.get("activities"), list):
        raise RuntimeError("Import response has no accepted activity list")
    by_key = {}
    for activity in submitted:
        key = (activity.get("accountId"), activity.get("comment"))
        if any(not isinstance(v, str) or not v for v in key) or key in by_key:
            raise RuntimeError("Ambiguous submitted import identity")
        by_key[key] = activity
    accepted = []
    seen = set()
    created_ids = set()
    for row in body["activities"]:
        if not isinstance(row, dict) or row.get("error"):
            raise RuntimeError("Invalid accepted import activity")
        key = (row.get("accountId"), row.get("comment"))
        if any(not isinstance(v, str) or not v for v in key) or key not in by_key or key in seen:
            raise RuntimeError("Unmatched or repeated accepted import identity")
        original = by_key[key]
        if not activity_is_active(row) or not activity_date_is_current(row):
            raise RuntimeError("Created activity is inactive; cannot update active holdings")
        # Preserve listing compatibility: current key wins, even if invalid.
        profile = (row["assetProfile"] if "assetProfile" in row
                   else row.get("SymbolProfile"))
        if (not isinstance(row.get("id"), str) or not row["id"].strip()
                or row["id"] in created_ids
                or not isinstance(profile, dict)
                or not isinstance(profile.get("symbol"), str) or not profile["symbol"].strip()
                or profile.get("dataSource") != original.get("dataSource")):
            raise RuntimeError("Accepted activity lacks created identity or matching data source")
        try:
            returned_date = datetime.fromisoformat(row["date"].replace("Z", "+00:00"))
            submitted_date = datetime.fromisoformat(original["date"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, TypeError, ValueError):
            raise RuntimeError("Accepted activity lacks a valid date") from None
        if (returned_date.tzinfo is None or submitted_date.tzinfo is None
                or returned_date != submitted_date):
            raise RuntimeError("Accepted activity has a different date")
        for field in ("quantity", "unitPrice", "fee"):
            for value in (row.get(field), original.get(field)):
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or value < 0):
                    raise RuntimeError("Accepted activity has invalid financial evidence")
        for field in ("type", "quantity", "unitPrice", "fee", "currency"):
            if row.get(field) != original.get(field):
                raise RuntimeError("Accepted activity differs from submitted financial evidence")
        seen.add(key)
        created_ids.add(row["id"])
        accepted.append({**original, "symbol": profile["symbol"]})
    return accepted


def mark_import_uncertain(config: Config, activities: list[dict[str, Any]]) -> None:
    """A POST may have written records; block later queries to these accounts."""
    config.setdefault("_uncertain_import_accounts", set()).update(
        a["accountId"] for a in activities if a.get("accountId"))


def ghost_import_activities(
    config: Config, activities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Import activities into Ghostfolio.  Returns (imported, ok).

    imported — the activities Ghostfolio accepted, for the caller's dedup
               bookkeeping; only rows identified in the server response.
               Dry-run returns the proposed rows for simulation only.
    ok       — True for a clean run, False when the run is degraded (a symbol
               was dropped) or failed, so the caller exits non-zero.

    Ghostfolio validates the whole /api/v1/import batch and aborts on the first
    activity whose symbol the data provider cannot resolve, failing trades and
    dividends alike with a single 400.  To stop one bad ticker from costing the
    whole account, such a 400 drops that symbol's activities, warns, and retries
    the reduced batch; the run still ends non-zero so the skipped symbol stays
    visible.  Other 400s (too many activities, premium, ...) are not per-symbol
    and fail hard without retrying.

    A 2xx response is clean only when it proves every submitted activity.  A
    shorter valid list preserves its exact accepted subset, fails the account
    without retrying, and tells the operator which comments need inspection.
    """
    if config.get("dry_run"):
        log_lab_evidence("preview", activities)
    if not activities:
        log.info("No new activities to import")
        return [], True
    if config.get("dry_run"):
        log.info("[DRY RUN] would import %d activities (no POST sent):", len(activities))
        for a in activities:
            log.info("[DRY RUN]   %-8s %-14s qty=%s price=%s %s fee=%s  %s",
                     a.get("type"), a.get("symbol"), a.get("quantity"),
                     a.get("unitPrice"), a.get("currency"), a.get("fee"),
                     a.get("comment"))
        return list(activities), True
    url = f"{config['ghost_host']}/api/v1/import"
    remaining = list(activities)
    dropped_symbols: list[str] = []
    # Each iteration drops one symbol, so the loop can never run more times than
    # there are distinct symbols (+1 for the final accepting POST).
    max_attempts = len({a.get("symbol") for a in activities}) + 1

    for _ in range(max_attempts):
        try:
            resp = requests.post(url, headers=ghost_headers(config["ghost_token"]),
                                 json={"activities": remaining}, timeout=60,
                                 allow_redirects=False)
        except requests.RequestException as exc:
            log.error("Import request failed: %s", exc)
            mark_import_uncertain(config, remaining)
            return [], False

        if ghost_response_is_redirect(resp):
            mark_import_uncertain(config, remaining)
            log.error(GHOST_REDIRECT_ERROR)
            return [], False

        try:
            body = resp.json()
        except ValueError:
            body = None

        if 200 <= resp.status_code < 300:
            try:
                imported = accepted_import_subset(remaining, body)
            except RuntimeError as exc:
                log.error("Cannot establish accepted import outcome: %s; inspect Ghostfolio before retry", exc)
                mark_import_uncertain(config, remaining)
                return [], False
            log.info("Ghostfolio created %d of %d submitted activities", len(imported), len(remaining))
            short_response = len(imported) < len(remaining)
            if short_response:
                accepted_keys = {
                    (activity["accountId"], activity["comment"])
                    for activity in imported
                }
                omitted_comments = [
                    activity["comment"] for activity in remaining
                    if (activity["accountId"], activity["comment"]) not in accepted_keys
                ]
                log.error(
                    "Ghostfolio accepted only %d of %d submitted activities; omitted comments: "
                    "%s — inspect Ghostfolio before rerun; the account failed and the batch "
                    "was not retried",
                    len(imported), len(remaining), ", ".join(omitted_comments),
                )
            if dropped_symbols:
                log.warning("Imported without %d unresolved symbol(s): %s — add a mapping entry "
                            "(symbol_mapping) so they are recognised next run",
                            len(dropped_symbols), ", ".join(dropped_symbols))
            return imported, not dropped_symbols and not short_response

        symbol = parse_unresolved_symbol(body, resp.text)
        if symbol is None:
            mark_import_uncertain(config, remaining)
            log.error("Import failed (%d): %s", resp.status_code, resp.text)
            log.error("Check your mapping file - a symbol may not be recognised by Ghostfolio")
            return [], False

        before = len(remaining)
        remaining = [a for a in remaining if a.get("symbol") != symbol]
        if before == len(remaining):
            # The named symbol matches no activity we can drop (e.g. a
            # server-side resolved name); retrying would loop forever.
            log.error("Ghostfolio rejected symbol %r but no matching activity was found to drop; "
                      "aborting import for this account. Response: %s", symbol, resp.text)
            return [], False
        dropped_symbols.append(symbol)
        log.warning("Ghostfolio cannot resolve symbol %r (%d activity/ies dropped); retrying without it",
                    symbol, before - len(remaining))
        if not remaining:
            log.warning("All activities were dropped as unresolved; nothing imported for this account")
            return [], False

    log.error("Import did not converge after dropping %d symbol(s): %s",
              len(dropped_symbols), ", ".join(dropped_symbols))
    return [], False


def ghost_update_cash_balance(
    config: Config, account_id: str, balance: float, base_currency: str | None,
) -> bool:
    """Update the cash balance on a Ghostfolio account.  Returns True on success.

    The GET response carries far more than the update DTO accepts (aggregations,
    relations, timestamps).  Ghostfolio 3.x validates bodies with
    forbidNonWhitelisted, so echoing it back is a hard 400.  The payload is
    therefore built explicitly from the five fields UpdateAccountDto requires:
    balance, currency, id, name and platformId (nullable).

    comment, tags and isExcluded are optional in the DTO and deliberately left
    out - Prisma does not touch a column that is absent from the update, so
    omitting them preserves the stored values.  For isExcluded that also keeps
    the payload portable: it was a deprecated DTO field up to Ghostfolio 3.38.0
    and removed in 3.39.0, so sending it fails outright on newer instances.

    The balance is the IBKR base-currency figure with no conversion, so the
    Ghostfolio account must have the same currency: a mismatch, or a report
    without a base currency, sends no PUT and returns False.  A dry run still
    does the read-only GET and the check, so the preview matches a live run.
    """
    if not base_currency:
        log.error("Cash balance not updated for account %s: the report has no base currency "
                  "(Account Information CurrencyPrimary missing from the Flex Query)", account_id)
        return False
    url = f"{config['ghost_host']}/api/v1/account/{account_id}"
    resp = requests.get(url, headers=ghost_headers(config["ghost_token"]), timeout=120,
                        allow_redirects=False)
    if ghost_response_is_redirect(resp):
        raise RuntimeError(GHOST_REDIRECT_ERROR)
    resp.raise_for_status()
    account_data = resp.json()

    if account_data["currency"] != base_currency:
        log.error("Cash balance not updated for account %s: IBKR base currency %s differs "
                  "from Ghostfolio account currency %s", account_id, base_currency,
                  account_data["currency"])
        return False
    log_lab_evidence("cash", {"accountId": account_id, "balance": balance, "currency": base_currency})
    if config.get("dry_run"):
        log.info("[DRY RUN] would set cash balance for account %s to %.2f (no PUT sent)",
                 account_id, balance)
        return True

    payload = {
        "balance": balance,
        "currency": account_data["currency"],
        "id": account_id,
        "name": account_data["name"],
        "platformId": account_data.get("platformId") or config.get("ghost_platform_id") or None,
    }
    resp = requests.put(url, headers=ghost_headers(config["ghost_token"]),
                        json=payload, timeout=30, allow_redirects=False)
    if ghost_response_is_redirect(resp):
        log.error(GHOST_REDIRECT_ERROR)
        return False
    if resp.status_code >= 400:
        log.error("Failed to update cash balance (%d): %s", resp.status_code, resp.text)
        return False
    log.info("Updated cash balance for account %s to %.2f", account_id, balance)
    return True


def log_lab_evidence(kind: str, value: object) -> None:
    """Expose existing targets at DEBUG without changing financial behavior."""
    if not log.isEnabledFor(logging.DEBUG):
        return
    try:
        message = json.dumps({"kind": kind, "value": value}, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        # Missing evidence fails lab acceptance; it must not change the operation.
        return
    log.debug("LAB_EVIDENCE %s", message)
