"""Sync operations; explicit functional boundaries."""

import csv
import io
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import ghostfolio_core as core
from ghostfolio_degiro_sync import accounting as accounting_module
from ghostfolio_degiro_sync import config as config_module
from ghostfolio_degiro_sync import degiro as degiro_module
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import ghostfolio as ghostfolio_module
from ghostfolio_degiro_sync import identity as identity_module
from ghostfolio_degiro_sync import journal as journal_module
from ghostfolio_degiro_sync.models import AccountSelection, SelectionResult


def synchronize_account(config: Any, snapshot: Any, target_account: Any, existing_body: Any, mapping: Any,
                        quote_currencies: Any, import_activities: Any, update_balance: Any, now: Any=None) -> Any:
    """Serialize live account work and preserve intent before every write."""
    if config.get("dry_run", True) is not False and config.get("sync_mode") not in ("prospective", "rolling"):
        return synchronize_locked(config, snapshot, target_account, existing_body, mapping,
            quote_currencies, import_activities, update_balance, now=now)
    with journal_module.account_journal(config) as journal:
        if config.get("sync_mode") == "rolling":
            journal_module.recover_confirmed_import(journal, config, existing_body)
        elif journal["document"]["pending"] is not None:
            raise RuntimeError("Unresolved durable write intent blocks account writes")
        return synchronize_locked(config, snapshot, target_account, existing_body, mapping,
            quote_currencies, import_activities, update_balance, now=now, journal=journal)


def select_account_activities(config: Any, snapshot: Any, target_account: Any, existing_body: Any, mapping: Any,
                        quote_currencies: Any, *, now: datetime, journal: Any=None, prospective_evidence: Any=None) -> AccountSelection:
    """Pure whole-account selection over supplied evidence and a fixed clock."""
    if now.tzinfo is None:
        raise RuntimeError("Selection requires an aware clock")
    dry_run = config.get("dry_run", True)
    if type(dry_run) is not bool:
        raise RuntimeError("Invalid DRY_RUN flag")
    if config.get("sync_mode", "full_history") not in ("full_history", "prospective", "rolling"):
        raise RuntimeError("Invalid synchronization mode")
    accounting_module.check_api_import_format(snapshot)
    source = identity_module.broker_identity(config.get("source_account"))
    if identity_module.broker_identity(snapshot.get("source_account")) != source:
        raise RuntimeError("DEGIRO configured source account mismatch")
    if not isinstance(target_account, dict) or target_account.get("id") != config.get("target_account"):
        raise RuntimeError("Ghostfolio configured target account mismatch")
    if not core.activity_is_active({"account": target_account}) or target_account.get("balance") is None:
        raise RuntimeError("Ghostfolio target account excluded or redacted")
    prospective = config.get("sync_mode", "full_history") == "prospective"
    rolling = config.get("sync_mode") == "rolling"
    profiles = dict(journal["document"].get("profiles", {})) if journal is not None else {}
    context: Any = None
    if prospective:
        snapshot, existing, quantities, context = prospective_snapshot(
            config, snapshot, target_account, existing_body, mapping, quote_currencies,
            evidence=prospective_evidence, now=now, profiles=profiles)
    else:
        existing, quantities = ghostfolio_module.index_existing_activities(existing_body, target_account, now=now)
    if rolling:
        snapshot = rolling_snapshot(snapshot, journal)
    balance = accounting_module.current_cash_balance(snapshot, target_account, source, now)
    if prospective:
        activities = context["activities"]
    else:
        activities = accounting_module.normalize_trades(snapshot, target_account["id"], mapping, quote_currencies)
        activities += accounting_module.normalize_dividends(snapshot, target_account["id"], mapping, quote_currencies)
        activities += accounting_module.normalize_fees(snapshot, target_account["id"])
        activities += accounting_module.normalize_cash_yield(snapshot, target_account["id"])
    if any(not ghostfolio_module.activity_date_is_current(activity, now) for activity in activities):
        raise RuntimeError("Future DEGIRO candidate blocks synchronization")
    if rolling and any(datetime.fromisoformat(a["date"]).microsecond % 1000 for a in activities):
        raise RuntimeError("Rolling date precision cannot be represented by Ghostfolio")
    existing, profiles = ghostfolio_module.bind_existing_profiles(existing, activities, profiles)
    if context:
        profiles.update(context.get("profiles", {}))
    exclusions = Counter({"already_imported": 0, "manual_match": 0, "duplicate_candidate": 0})
    pending = ghostfolio_module.pending_activities(activities, existing, target_account, source, manual_matching=rolling,
                                 exclusions=exclusions)
    trades = [activity for activity in pending if activity["type"] in ("BUY", "SELL")]
    accounting_module.reconcile_trade_holdings(trades, [row for row in existing if str(row.get("comment") or "").startswith("DEGIRO#")]
                             if rolling else existing, quantities)
    if rolling:
        expected = dict(quantities)
        for activity in trades:
            key = (target_account["id"], activity["symbol"])
            expected[key] = expected.get(key, Decimal(0)) + accounting_module.financial_decimal(activity["quantity"]) * (
                1 if activity["type"] == "BUY" else -1)
        if nonzero_holdings(expected) != broker_stock_holdings(snapshot, target_account, mapping, quote_currencies):
            raise RuntimeError("Rolling broker holdings do not reconcile")
        known = {identity_module.parse_identity(a["comment"], a["type"]): ghostfolio_module.ownership_signature(a) for a in activities}
        start = date.fromisoformat(snapshot["from_date"])

        for row in existing:
            if (row["accountId"] == target_account["id"] and (owned_key := identity_module.parse_identity(row.get("comment"), row.get("type"))) is not None
                    and owned_key[0] == source
                    and accounting_module.prospective_instant(row["date"]).astimezone(ZoneInfo("Europe/Zurich")).date() >= start
                    and known.get(identity_module.parse_identity(row["comment"], row["type"])) != ghostfolio_module.ownership_signature(row)):
                raise RuntimeError("Unproved rolling destination activity")
    if not dry_run and not prospective and not rolling and snapshot.get("history_completeness_verified") is not True:
        raise RuntimeError("Unverified DEGIRO history completeness blocks live writes")
    if target_account["id"] in config.get("_uncertain_import_accounts", set()):
        raise RuntimeError("Uncertain prior import blocks account writes")
    return AccountSelection(
        selection=SelectionResult(proposals=tuple(pending), rejected=(), deferred=(),
            holdings=tuple((account, symbol, value) for (account, symbol), value in sorted(quantities.items()))),
        snapshot=snapshot, cash=balance, candidates=len(activities), exclusions=dict(exclusions),
        prospective=prospective, rolling=rolling, context=context, profiles=profiles)


def synchronize_locked(config: Any, snapshot: Any, target_account: Any, existing_body: Any, mapping: Any,
                        quote_currencies: Any, import_activities: Any, update_balance: Any,
                        now: datetime | None=None, journal: Any=None) -> Any:
    """Dispatch selected proposals; record holdings only after accepted evidence."""
    now = datetime.now(UTC) if now is None else now
    evidence = (journal_module.load_prospective_evidence(config["cutover_manifest"], config["cutover_sha256"])
        if config.get("sync_mode") == "prospective" else None)
    plan = select_account_activities(config, snapshot, target_account, existing_body, mapping,
        quote_currencies, now=now, journal=journal, prospective_evidence=evidence)
    pending = [dict(row) for row in plan.selection.proposals]
    quantities = {(account, symbol): value for account, symbol, value in plan.selection.holdings}
    snapshot, balance, context = plan.snapshot, plan.cash, plan.context
    prospective, rolling = plan.prospective, plan.rolling
    dry_run, source = config.get("dry_run", True), config["source_account"]
    if dry_run:
        return {"proposed": pending, "accepted": [], "cash": balance, "dry_run": True,
                "cash_before": float(accounting_module.financial_decimal(target_account["balance"])),
                "candidates": plan.candidates, "exclusions": dict(plan.exclusions),
                "period": {"from_date": snapshot.get("from_date"), "to_date": snapshot.get("to_date"),
                           "timezone": "Europe/Zurich"},
                "history_verified": snapshot.get("history_completeness_verified") is True,
                "prospective_verified": prospective,
                "rolling_verified": rolling,
                "cutover": context["cutover"].isoformat() if context else None,
                "basis_status": context["basis_status"] if context else None}
    if journal is not None and plan.profiles:
        journal["document"]["profiles"] = dict(plan.profiles)
        journal_module.write_journal(journal)
    accepted = []
    for sells in (False, True):
        batch = [activity for activity in pending if (activity["type"] == "SELL") == sells]
        if not batch:
            continue
        if sells:
            accounting_module.reconcile_trade_holdings(batch, [], quantities)
        try:
            intent = journal_module.begin_intent(journal, "import", {a["comment"]: a for a in batch})
            created, ok = import_activities(batch)
            if not isinstance(created, list):
                raise RuntimeError("Invalid accepted account import evidence")
            created, profiles = ghostfolio_module.prove_accepted_subset(batch, created)
            if journal is not None:
                journal_module.record_confirmed_import(journal, intent, created, profiles)
            quantities = ghostfolio_module.record_accepted_activities(created, quantities)
            accepted.extend(created)
            if ok is not True or len(created) != len(batch):
                raise RuntimeError("Incomplete accepted account import evidence")
            journal_module.confirm_intent(journal, intent)
        except Exception:
            core.mark_import_uncertain(config, batch)
            raise RuntimeError("Account import uncertain or incomplete; cash blocked") from None
    def guarded_balance(account: Any, amount: Any) -> Any:
        intent = journal_module.begin_intent(journal, "cash", {"account": account, "balance": amount})
        try:
            if update_balance(account, amount) is not True:
                raise RuntimeError("Cash update rejected")
            journal_module.confirm_intent(journal, intent)
        except Exception:
            raise RuntimeError("Uncertain cash update remains durably fenced") from None
        return True

    accounting_module.apply_cash_balance(snapshot, target_account, source, guarded_balance, dry_run=False,
        import_ok=True, uncertain=target_account["id"] in config.get("_uncertain_import_accounts", set()), now=now)
    if rolling:
        journal["document"]["coverage"] = {"from_date": snapshot["from_date"], "through": snapshot["fetched_at"]}
        journal_module.write_journal(journal)
    return {"proposed": pending, "accepted": accepted, "cash": balance, "dry_run": False,
            "history_verified": not prospective and not rolling, "prospective_verified": prospective,
            "rolling_verified": rolling,
            "cutover": context["cutover"].isoformat() if context else None,
            "basis_status": context["basis_status"] if context else None}


def broker_stock_holdings(snapshot: Any, target_account: Any, mapping: Any, quote_currencies: Any) -> Any:
    """Decode every held security; missing metadata, units or instruments block."""
    quantities: dict[tuple[str, str], Decimal] = {}
    identities: set[object] = set()
    for row in accounting_module.cash_wrapper_rows(snapshot["update"], "portfolio"):
        fields = accounting_module.named_values(row["value"])
        identity = row.get("id")
        if identity in identities or fields.get("id") != identity:
            raise RuntimeError("Conflicting prospective holding identity")
        identities.add(identity)
        size = accounting_module.financial_decimal(fields.get("size"))
        if isinstance(identity, str) and identity.startswith("FLATEX_"):
            continue  # Independently checked by current_cash_balance.
        if (identity in accounting_module.CASH_CURRENCIES
                and fields.get("positionType") == "CASH" and size == 0):
            continue  # Empty currency placeholders are not held securities.
        product_id = identity_module.broker_identity(identity)
        if size == 0:
            continue
        product = snapshot["products"].get(product_id)
        if (not isinstance(product, dict) or identity_module.broker_identity(product.get("id")) != product_id
                or product.get("productType") != "STOCK"
                or accounting_module.financial_decimal(product.get("contractSize")) != 1 or size < 0
                or not accounting_module.valid_isin(product.get("isin"))):
            raise RuntimeError("Unverified prospective security holding")
        symbol = mapping.get(product["isin"])
        if (not isinstance(symbol, str) or not symbol.strip()
                or quote_currencies.get(symbol) != product.get("currency")):
            raise RuntimeError("Unverified prospective holding mapping")
        key = (target_account["id"], symbol)
        quantities[key] = quantities.get(key, Decimal(0)) + size
    return {key: value for key, value in quantities.items() if value != 0}


def nonzero_holdings(quantities: Any) -> Any:
    return {key: value for key, value in quantities.items() if value != 0}


def prospective_opening_context(evidence: Any, config: Any, mapping: Any, quote_currencies: Any, now: datetime | None=None) -> Any:
    """Verify unchanged opening inventory without manufacturing destination rows."""
    try:
        manifest, captures = evidence["manifest"], evidence["captures"]
        if (manifest["source_account"] != identity_module.broker_identity(config["source_account"])
                or manifest["target_account"] != config["target_account"]
                or manifest["mapping_sha256"] != journal_module.evidence_digest({
                    "mapping": mapping, "quote_currencies": quote_currencies})
                or len(set(mapping.values())) != len(mapping)):
            raise RuntimeError("Prospective account or mapping binding mismatch")
        opening = captures["broker"]
        destination = captures["destination"]
        target = destination["account"]
        cutover = accounting_module.prospective_instant(manifest["cutover"])
        started = accounting_module.prospective_instant(opening["fetch_started_at"])
        fetched = accounting_module.prospective_instant(opening["fetched_at"])
        captured = accounting_module.prospective_instant(destination["captured_at"])
        if (cutover != fetched or not started <= captured <= fetched
                or fetched - started > timedelta(minutes=5)
                or target["id"] != config["target_account"]):
            raise RuntimeError("Unproved prospective opening capture interval")
        cash = accounting_module.current_cash_balance(opening, target, config["source_account"], now=fetched)
        accounting_module.financial_decimal(target["balance"])  # Existing cash may be stale; broker cash is authoritative.
        rows, quantities = ghostfolio_module.index_existing_activities(destination["activities"], target, now=now)
        protected = {}
        for row in rows:
            if row["accountId"] != target["id"]:
                continue
            instant = datetime.fromisoformat(accounting_module.broker_instant(row["date"]))
            if instant > started:
                raise RuntimeError("Concurrent prospective destination opening event")
            # Legacy monetary fields are protected, not certified. Opening
            # inventory is proved below through exact current broker quantities.
            protected[row["id"]] = journal_module.evidence_digest({
                "signature": [str(value) for value in accounting_module.activity_signature(row)],
                "id": row["id"]})
        for row in opening["transactions"] + opening["cash_movements"]:
            if accounting_module.prospective_instant(row["date"]) > started:
                raise RuntimeError("Concurrent prospective broker opening event")
        if nonzero_holdings(quantities) != broker_stock_holdings(
                opening, target, mapping, quote_currencies):
            raise RuntimeError("Prospective opening holdings mismatch")
        return {"cutover": cutover, "opening": opening, "protected": protected,
                "quantities": quantities, "cash": cash, "basis_status": "unverified"}
    except (KeyError, TypeError, AttributeError, ValueError):
        raise RuntimeError("Incomplete prospective opening evidence") from None


def execution_cash_matches(trade: Any, row: Any, product: Any, statement_amount: Any=None) -> Any:
    """Keep exact identity; corroborate cent rounding through signed execution gross."""
    side = trade.get("buysell")
    if (side not in ("B", "S") or row.get("type") != "TRANSACTION"
            or identity_module.broker_identity(row.get("productId")) != identity_module.broker_identity(trade["productId"])
            or accounting_module.broker_instant(row["date"]) != accounting_module.broker_instant(trade["date"])
            or row["currency"] != product["currency"]
            or not row["description"].startswith("Achat " if side == "B" else "Vente ")
            or (trade.get("orderId") is not None and row.get("orderId") != trade["orderId"])):
        return False
    amounts = [accounting_module.financial_decimal(trade["total"]), accounting_module.financial_decimal(row["change"])]
    if statement_amount is not None:
        amounts.append(accounting_module.financial_decimal(statement_amount))
    if len(set(amounts)) == 1:
        return True
    cent = Decimal("0.01")
    if (accounting_module.CURRENCY_QUANTA.get(product["currency"]) != cent
            or product.get("productType") != "STOCK"
            or accounting_module.financial_decimal(product.get("contractSize")) != 1
            or any(amount % cent != 0 for amount in amounts[1:])
            or max(amounts) - min(amounts) > cent):
        return False
    quantity, price = accounting_module.financial_decimal(trade["quantity"]), accounting_module.financial_decimal(trade["price"])
    if (not quantity or price <= 0 or (side == "B" and quantity <= 0)
            or (side == "S" and quantity >= 0)):
        return False
    gross = -quantity * price
    return all(amount * gross > 0 and abs(amount - gross) <= cent for amount in amounts)


def prospective_statement_matches(snapshot: Any) -> Any:
    """Preserve the raw cash multiset; corroborate only bounded execution rounding."""
    header = ["Date", "Heure", "Date de", "Produit", "Code ISIN", "Description",
              "FX", "Mouvements", "", "Solde", "", "ID Ordre"]
    try:
        text = snapshot["account_report_csv"]
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or rows[0] != header:
            raise RuntimeError("Unverified prospective statement header")
        statement = []
        for row in rows[1:]:
            if len(row) != 12:
                raise RuntimeError("Unverified prospective statement row")
            datetime.strptime(row[0], "%d-%m-%Y")
            datetime.strptime(row[1], "%H:%M")
            datetime.strptime(row[2], "%d-%m-%Y")
            statement.append((row[0], row[1], row[2], row[4], row[5], row[7],
                accounting_module.financial_decimal(row[8].replace(",", ".")) if row[8] else None, row[11]))
        source = []
        for row in snapshot["cash_movements"]:
            datetime.fromisoformat(accounting_module.broker_instant(row["date"]))
            # Preserve the broker offset for the separately corroborated statement clock.
            local = datetime.fromisoformat(row["date"])
            datetime.fromisoformat(accounting_module.broker_instant(row["valueDate"]))
            local_value = datetime.fromisoformat(row["valueDate"])
            product = snapshot["products"].get(str(row.get("productId")), {})
            source.append((local.strftime("%d-%m-%Y"), local.strftime("%H:%M"),
                local_value.strftime("%d-%m-%Y"), product.get("isin", ""), row["description"],
                row.get("currency", "") if row.get("change") is not None else "",
                accounting_module.financial_decimal(row["change"]) if row.get("change") is not None else None,
                str(row.get("orderId") or "")))
        unmatched_source = list((Counter(source) - Counter(statement)).elements())
        unmatched_statement = list((Counter(statement) - Counter(source)).elements())
        for item in unmatched_source:
            cash_rows = [row for row, signature in zip(snapshot["cash_movements"], source, strict=False)
                if signature == item]
            candidates = [candidate for candidate in unmatched_statement
                if item[:6] + item[7:] == candidate[:6] + candidate[7:]
                and item[6] is not None and candidate[6] is not None]
            if len(cash_rows) != 1 or len(candidates) != 1:
                raise RuntimeError("Prospective statement coverage mismatch")
            row, candidate = cash_rows[0], candidates[0]
            trades = [trade for trade in snapshot["transactions"]
                if execution_cash_matches(trade, row,
                    snapshot["products"][identity_module.broker_identity(trade["productId"])], candidate[6])]
            exact = [trade for trade in trades
                if accounting_module.financial_decimal(trade["total"]) == accounting_module.financial_decimal(row["change"])]
            trades = exact or trades
            if len(trades) != 1:
                raise RuntimeError("Prospective statement coverage mismatch")
            unmatched_statement.remove(candidate)
        if unmatched_statement:
            raise RuntimeError("Prospective statement coverage mismatch")
        if unmatched_source:
            diagnostics_module.log.info("Cash statement verified with %d corroborated one-cent execution rounding differences",
                     len(unmatched_source))
        return len(source)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Incomplete prospective statement evidence") from None


def prospective_execution_cash(snapshot: Any) -> Any:
    """Each execution needs unique signed cash, allowing only corroborated cent rounding."""
    ledger = accounting_module.classify_cash_movements(snapshot["cash_movements"])["executed_trade_cash"]
    remaining = list(ledger)
    for trade in snapshot["transactions"]:
        product = snapshot["products"][identity_module.broker_identity(trade["productId"])]
        candidates = [row for row in remaining if execution_cash_matches(trade, row, product)]
        exact = [row for row in candidates
            if accounting_module.financial_decimal(row["change"]) == accounting_module.financial_decimal(trade["total"])]
        candidates = exact or candidates
        if len(candidates) != 1:
            raise RuntimeError("Unproved prospective execution cash relation")
        remaining.remove(candidates[0])
    if remaining:
        raise RuntimeError("Prospective cash execution missing from trade feed")


def rolling_snapshot(snapshot: Any, journal: Any) -> Any:
    """Validate bounded rolling/catch-up coverage without historical claims."""
    try:
        result = dict(snapshot)
        fetched = accounting_module.prospective_instant(snapshot["fetched_at"])
        today = fetched.astimezone(ZoneInfo("Europe/Zurich")).date()
        start, end = date.fromisoformat(snapshot["from_date"]), date.fromisoformat(snapshot["to_date"])
        if start > today - timedelta(days=89) or end != today:
            raise RuntimeError("Incomplete rolling interval coverage")
        coverage = journal["document"].get("coverage") if journal else None
        if coverage:
            last = accounting_module.prospective_instant(coverage["through"])
            if last > fetched or start > last.astimezone(ZoneInfo("Europe/Zurich")).date():
                raise RuntimeError("Rolling coverage gap requires explicit catch-up start")
        for collection in ("transactions", "cash_movements"):
            rows: list[dict[str, Any]] = []
            accounting_module.merge_history(rows, snapshot[collection], cash=collection == "cash_movements")
            for row in rows:
                instant = accounting_module.prospective_instant(row["date"])
                if instant > fetched or instant.astimezone(ZoneInfo("Europe/Zurich")).date() < start:
                    raise RuntimeError("Rolling source event outside verified interval")
                if collection == "cash_movements" and row.get("change") is not None:
                    if accounting_module.prospective_instant(row["valueDate"]) > fetched:
                        raise RuntimeError("Future rolling cash value date")
            result[collection] = rows
        prospective_statement_matches(result)
        prospective_execution_cash(result)
        result["history_completeness_verified"] = False
        return result
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Incomplete rolling account evidence") from None


def prospective_snapshot(config: Any, snapshot: Any, target: Any, existing_body: Any, mapping: Any, quotes: Any,
                         *, evidence: Any=None, now: datetime | None=None, profiles: Any=None) -> Any:
    """Reconcile a full interval from a fixed cutover; never relabel full history."""
    try:
        if evidence is None:
            raise RuntimeError("Prospective selection requires supplied evidence")
        context = prospective_opening_context(evidence, config, mapping, quotes, now=now)
        cutover, opening = context["cutover"], context["opening"]
        if (identity_module.broker_identity(snapshot["source_account"]) != identity_module.broker_identity(config["source_account"])
                or target["id"] != config["target_account"]):
            raise RuntimeError("Prospective source or target mismatch")
        fetched = accounting_module.prospective_instant(snapshot["fetched_at"])
        # Full replay since cutover deliberately avoids a mutable coverage checkpoint.
        boundary = cutover.astimezone(ZoneInfo("Europe/Zurich")).date()
        if (snapshot["from_date"] != opening["from_date"]
                or date.fromisoformat(snapshot["to_date"]) < fetched.astimezone(ZoneInfo("Europe/Zurich")).date()
                or date.fromisoformat(opening["from_date"]) > boundary
                or date.fromisoformat(opening["to_date"]) < boundary or fetched < cutover):
            raise RuntimeError("Incomplete prospective interval coverage")
        accounting_module.check_api_import_format(snapshot)
        snapshot = dict(snapshot)
        for collection in ("transactions", "cash_movements"):
            unique: list[dict[str, Any]] = []
            accounting_module.merge_history(unique, snapshot[collection], cash=collection == "cash_movements")
            snapshot[collection] = unique
        prospective_statement_matches(snapshot)
        rows, destination_quantities = ghostfolio_module.index_existing_activities(existing_body, target, now=now)
        protected = context["protected"]
        present = {}
        prospective_existing = []
        for row in rows:
            if row["accountId"] != target["id"]:
                prospective_existing.append(row)
                continue
            if datetime.fromisoformat(accounting_module.broker_instant(row["date"])) <= cutover:
                present[row["id"]] = journal_module.evidence_digest({
                    "signature": [str(value) for value in accounting_module.activity_signature(row)], "id": row["id"]})
            else:
                prospective_existing.append(row)
        if present != protected:
            raise RuntimeError("Protected prospective legacy history changed")
        result = dict(snapshot)
        result["history_completeness_verified"] = False
        for collection in ("transactions", "cash_movements"):
            before = opening[collection]
            actual = [row for row in snapshot[collection]
                if accounting_module.prospective_instant(row["date"]) <= cutover]
            def signatures(items: Any, collection: str=collection) -> Any:
                return Counter(journal_module.evidence_digest({key: value for key, value in row.items()
                    if collection != "cash_movements" or key != "balance"}) for row in items)
            if signatures(before) != signatures(actual):
                raise RuntimeError("Late or changed pre-cutover source event")
            result[collection] = [row for row in snapshot[collection]
                if accounting_module.prospective_instant(row["date"]) > cutover]
            for row in result[collection]:
                instant = accounting_module.prospective_instant(row["date"])
                if instant > fetched:
                    raise RuntimeError("Future prospective source event")
                if collection == "cash_movements" and row.get("change") is not None:
                    value = accounting_module.prospective_instant(row["valueDate"])
                    if value <= cutover or value > fetched:
                        raise RuntimeError("Ambiguous prospective value-date boundary")
        prospective_execution_cash(result)
        activities = accounting_module.normalize_trades(result, target["id"], mapping, quotes)
        activities += accounting_module.normalize_dividends(result, target["id"], mapping, quotes)
        activities += accounting_module.normalize_fees(result, target["id"])
        activities += accounting_module.normalize_cash_yield(result, target["id"])
        if any(datetime.fromisoformat(activity["date"]).microsecond % 1000 for activity in activities):
            raise RuntimeError("Prospective date precision cannot be represented by Ghostfolio")
        prospective_existing, associations = ghostfolio_module.bind_existing_profiles(prospective_existing, activities, profiles or {})
        context["profiles"] = associations
        # Every existing post-cutover target row must be evidenced by this full replay.
        ghostfolio_module.pending_activities(activities, prospective_existing, target, config["source_account"])
        known = {identity_module.parse_identity(row["comment"], row["type"]): ghostfolio_module.ownership_signature(row) for row in activities}
        for row in prospective_existing:
            if row["accountId"] == target["id"] and (
                    identity_module.parse_identity(row.get("comment"), row.get("type")) not in known
                    or known[identity_module.parse_identity(row["comment"], row["type"])] != ghostfolio_module.ownership_signature(row)):
                raise RuntimeError("Unproved post-cutover destination activity")
        expected = dict(context["quantities"])
        for activity in activities:
            if activity["type"] in ("BUY", "SELL"):
                key = (target["id"], activity["symbol"])
                expected[key] = expected.get(key, Decimal(0)) + accounting_module.financial_decimal(activity["quantity"]) * (
                    1 if activity["type"] == "BUY" else -1)
        if nonzero_holdings(expected) != broker_stock_holdings(snapshot, target, mapping, quotes):
            raise RuntimeError("Prospective broker holdings do not reconcile")
        context["activities"] = activities
        result["prospective_verified"] = True
        return result, prospective_existing, destination_quantities, context
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Incomplete prospective account evidence") from None


def run_sync(from_date: Any, to_date: Any, window_days: Any=90) -> Any:
    """One broker read and complete target read; no completeness assertion invented."""
    config, mapping, quotes = config_module.load_sync_config()
    if config["dry_run"] and config.get("sync_mode") not in ("prospective", "rolling"):
        with diagnostics_module.diagnostic_boundary("sync", "reconciliation"):
            return run_sync_locked(config, mapping, quotes, from_date, to_date, window_days)
    with diagnostics_module.diagnostic_boundary("config", "state_dir"), journal_module.account_journal(config) as journal:
        with diagnostics_module.diagnostic_boundary("sync", "reconciliation"):
            if journal["document"]["pending"] is not None and config.get("sync_mode") != "rolling":
                raise RuntimeError("Unresolved durable write intent blocks account writes")
            return run_sync_locked(config, mapping, quotes, from_date, to_date, window_days, journal)


def run_sync_locked(config: Any, mapping: Any, quotes: Any, from_date: Any, to_date: Any, window_days: Any, journal: Any=None) -> Any:
    """Live lock covers source/target reads as well as dispatch."""
    if config.get("sync_mode") == "prospective":
        evidence = journal_module.load_prospective_evidence(config["cutover_manifest"], config["cutover_sha256"])
        context = prospective_opening_context(evidence, config, mapping, quotes)
        from_date = date.fromisoformat(context["opening"]["from_date"])
        to_date = max(to_date, datetime.now(ZoneInfo("Europe/Zurich")).date())
        degiro_module.history_windows(from_date, to_date, window_days)
        ghostfolio_module.authenticate_ghostfolio(config)
        snapshot = degiro_module.read_degiro(from_date, to_date, window_days,
            report_locale=("fr", "fr"), holdings=True)
    elif config.get("sync_mode") == "rolling":
        today = datetime.now(ZoneInfo("Europe/Zurich")).date()
        if to_date != today or from_date > today - timedelta(days=89):
            raise RuntimeError("Rolling mode requires 90 days through broker-local today")
        coverage = journal["document"].get("coverage")
        if coverage and from_date > accounting_module.prospective_instant(coverage["through"]).astimezone(ZoneInfo("Europe/Zurich")).date():
            raise RuntimeError("Rolling coverage gap requires explicit catch-up start")
        degiro_module.history_windows(from_date, to_date, window_days)
        ghostfolio_module.authenticate_ghostfolio(config)
        snapshot = degiro_module.read_degiro(from_date, to_date, window_days, report_locale=("fr", "fr"), holdings=True)
    else:
        degiro_module.history_windows(from_date, to_date, window_days)
        ghostfolio_module.authenticate_ghostfolio(config)
        snapshot = degiro_module.read_degiro(from_date, to_date, window_days)
    expected_target = {"id": config["target_account"], "currency": snapshot["account_info"]["baseCurrency"]}
    with diagnostics_module.diagnostic_boundary("ghostfolio", "transport"), ghostfolio_module.ghost_transport(config, expected_target) as session:
        with diagnostics_module.diagnostic_boundary("ghostfolio", "account_read"):
            response = session.get(f"{config['ghost_host']}/api/v1/account/{config['target_account']}")
            response.raise_for_status()
            target = response.json()
        with diagnostics_module.diagnostic_boundary("ghostfolio", "activities_read"):
            response = session.get(f"{config['ghost_host']}/api/v1/activities")
            response.raise_for_status()
            existing = response.json()
        with diagnostics_module.diagnostic_boundary("sync", "reconciliation"):
            if config.get("sync_mode") == "rolling":
                journal_module.recover_confirmed_import(journal, config, existing)
            return synchronize_locked(config, snapshot, target, existing, mapping, quotes,
                lambda activities: core.ghost_import_activities(config, activities),
                lambda account, balance: core.ghost_update_cash_balance(config, account, balance, snapshot["account_info"]["baseCurrency"]), journal=journal)
