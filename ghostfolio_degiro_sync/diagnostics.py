"""Fixed public diagnostic boundaries and private library logging."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

AUTH_FAILURE_REASONS = ("transport_error", "timeout", "tls_error", "redirect_refused",
                        "maintenance", "captcha_required", "totp_required", "in_app_required",
                        "http_400", "http_401", "http_403", "http_429", "http_5xx",
                        "invalid_login_response", "broker_rejected")
BROKER_READ_STAGES = ("login", "client_discovery", "transactions", "account_overview",
                      "products", "account_info", "account_update", "account_report",
                      "order_history", "cutover_destination", "logout")
# Public diagnostic tokens are fixed; never derive them from external text.
FAILURE_DIAGNOSTICS = frozenset(
    [("config", reason) for reason in ("arguments", "mode", "date_range", "window_days",
        "lookback_days", "report_locale", "mapping", "state_dir", "account",
        "sync_mode", "ghostfolio_credentials", "direct_credentials", "broker_credentials")]
    + [("vault", reason) for reason in ("configuration", "temporary_state", "server",
        "login", "unlock", "sync", "item", "logout")]
    + [(stage, "failed") for stage in BROKER_READ_STAGES]
    + [("login", reason) for reason in AUTH_FAILURE_REASONS]
    + [("broker", "read"), ("broker", "api_format"), ("sync", "reconciliation"),
       ("sync", "failed"), ("output", "destination"), ("output", "write"),
       ("ghostfolio", "authentication"), ("ghostfolio", "transport"),
       ("ghostfolio", "account_read"), ("ghostfolio", "activities_read")])


def failure_diagnostic(error: Any) -> Any:
    """Revalidate even attached metadata before rendering it publicly."""
    value = getattr(error, "sync_diagnostic", None)
    if (type(value) is tuple and len(value) == 2
            and all(type(part) is str for part in value) and value in FAILURE_DIAGNOSTICS):
        return value
    return None


def tag_failure(error: Any, stage: Any, reason: Any) -> Any:
    """Keep the earliest known boundary while leaving exception semantics intact."""
    if failure_diagnostic(error) is None and (stage, reason) in FAILURE_DIAGNOSTICS:
        error.sync_diagnostic = (stage, reason)
    return error


@contextmanager
def diagnostic_boundary(stage: Any, reason: Any) -> Iterator[None]:
    try:
        yield
    except Exception as error:
        tag_failure(error, stage, reason)
        raise


def log_failure(message: Any, error: Any, fallback: Any=("sync", "failed")) -> Any:
    stage, reason = failure_diagnostic(error) or fallback
    log.error("%s; stage=%s reason=%s", message, stage, reason)


@contextmanager
def private_broker_logs() -> Iterator[None]:
    """Mute broker and HTTP diagnostics during secret-bearing operations."""
    names = {"degiro_connector", "urllib3", "requests", "charset_normalizer"}
    names.update(name for name in logging.root.manager.loggerDict
                 if name.startswith(("degiro_connector.", "urllib3.", "requests.", "charset_normalizer.")))
    saved = []
    for name in names:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level, logger.disabled, logger.propagate))
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True
        logger.propagate = False
    try:
        yield
    finally:
        for logger, level, disabled, propagate in saved:
            logger.setLevel(level)
            logger.disabled = disabled
            logger.propagate = propagate


def reconcile_activities(expected: list[dict[str, Any]], observed: list[dict[str, Any]],
        from_date: str | None, to_date: str | None, *, exact: bool=True) -> list[dict[str, Any]]:
    """Account for each pre-deduplication event once without changing selection."""
    from ghostfolio_degiro_sync import accounting, identity
    def key(row: dict[str, Any]) -> tuple[str, str, str] | None:
        try:
            return identity.parse_identity(row.get('comment'), row.get('type'))
        except RuntimeError:
            return None
    def day(row: dict[str, Any]) -> str | None:
        try:
            return accounting.broker_instant(row.get('date'))[:10]
        except RuntimeError:
            return None
    source: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    destination: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    unknown_expected, unknown_observed = [], []
    for row in expected:
        owner = key(row)
        if owner is None:
            unknown_expected.append(row)
        else:
            source.setdefault(owner, []).append(row)
    for row in observed:
        owner = key(row)
        if owner is None:
            unknown_observed.append(row)
        else:
            destination.setdefault(owner, []).append(row)
    result = []
    for owner in dict.fromkeys([*source, *destination]):
        proposals, rows = source.get(owner, []), destination.get(owner, [])
        proposal = proposals[0] if len(proposals) == 1 else None
        stored = rows[0] if len(rows) == 1 else None
        status = 'uncertain'
        checks: dict[str, str] = {}
        for field in ('accountId', 'date', 'type', 'currency', 'dataSource', 'symbol', 'quantity', 'unitPrice', 'fee'):
            left, right = (proposal or {}).get(field), (stored or {}).get(field)
            try:
                if field in ('quantity', 'unitPrice', 'fee'):
                    left, right = accounting.financial_decimal(left), accounting.financial_decimal(right)
                elif field == 'date':
                    left, right = accounting.broker_instant(left), accounting.broker_instant(right)
                if left is None or right is None or (field == 'currency' and (
                        left not in accounting.CURRENCY_QUANTA or right not in accounting.CURRENCY_QUANTA)):
                    checks[field] = 'unavailable'
                else:
                    checks[field] = 'equal' if left == right else 'different'
            except RuntimeError:
                checks[field] = 'unavailable'
        reference = proposal or stored or {}
        date_value = day(reference)
        outside = (not proposals and date_value is not None and from_date is not None
                   and to_date is not None and not from_date <= date_value <= to_date)
        if outside:
            status = 'outside-window'
        elif exact and len(proposals) == len(rows) == 1 and all(value != 'unavailable' for value in checks.values()):
            status = 'coherent' if all(value == 'equal' for value in checks.values()) else 'to-check'
        elif exact and len(proposals) == 1 and not rows:
            status = 'informational'
        result.append({'identity': ':'.join(owner), 'status': status, 'expected': proposal,
            'observed': stored, 'observed_ids': [row.get('id') for row in rows],
            'source_count': len(proposals), 'target': stored.get('id') if stored and len(proposals) == 1 else None,
            'checks': checks, 'security_quantity': (proposal.get('quantity') if proposal and
                proposal.get('type') in ('BUY', 'SELL') and exact and proposal.get('currency') in accounting.CURRENCY_QUANTA else None),
            'reason': 'Exact source ownership' if status == 'coherent' else
                'Source ownership or financial evidence needs inspection' if status in ('uncertain', 'to-check') else
                'Outside proven source interval' if outside else 'No owned destination activity',
            'exact': exact})
    for row in unknown_expected:
        result.append({'identity': None, 'status': 'uncertain', 'expected': row, 'observed': None,
            'observed_ids': [], 'source_count': 1, 'target': None, 'checks': {}, 'security_quantity': None,
            'reason': 'Unavailable source ownership', 'exact': exact})
    for row in unknown_observed:
        result.append({'identity': None, 'status': 'informational', 'expected': None, 'observed': row,
            'observed_ids': [row.get('id')], 'source_count': 0, 'target': None, 'checks': {},
            'security_quantity': None, 'reason': 'Manual or other broker; no ownership claim', 'exact': exact})
    return result


def exact_json(raw: object) -> Any:
    import json
    from decimal import Decimal
    if not isinstance(raw, (bytes, str)) or not raw:
        return None
    try:
        return json.loads(raw, parse_float=Decimal)
    except (ValueError, UnicodeError):
        return None


def exact_source_activities(snapshot: dict[str, Any], target: str, mapping: dict[str, str],
        quotes: dict[str, str]) -> list[dict[str, Any]] | None:
    """Use original wire decimals, never reconstruct precision from floats."""
    from ghostfolio_degiro_sync import accounting, identity
    wires = snapshot.get('_diagnostic_wire')
    if not isinstance(wires, list):
        return None
    exact = {**snapshot, 'transactions': [], 'cash_movements': [], 'products': {}}
    found = set()
    try:
        for item in wires:
            body = exact_json(item['body'])
            if not isinstance(body, dict):
                return None
            path = item['path']
            if path.endswith('/transactions'):
                accounting.merge_history(exact['transactions'], body['data'])
                found.add('transactions')
            elif path.endswith('/accountoverview'):
                accounting.merge_history(exact['cash_movements'], body['data']['cashMovements'], cash=True)
                found.add('cash_movements')
            elif path.endswith('/products/info'):
                exact['products'].update(body['data'])
        if found != {'transactions', 'cash_movements'}:
            return None
        # Normalize with the existing accounting gates, then restore exact fields
        # from the proven original source rows rather than their float payload.
        activities = accounting.normalize_trades(exact, target, mapping, quotes)
        activities += accounting.normalize_dividends(exact, target, mapping, quotes)
        activities += accounting.normalize_fees(exact, target)
        activities += accounting.normalize_cash_yield(exact, target)
        trades = {str(row['id']): row for row in exact['transactions']}
        cash = {str(row['id']): row for row in exact['cash_movements']}
        classified = accounting.classify_cash_movements(exact['cash_movements'], accounting.load_cash_rules())
        dividends = {str(row['id']): tax for row, tax in accounting.associate_dividends(classified)}
        result = []
        for activity in activities:
            owner = identity.parse_identity(activity['comment'], activity['type'])
            if owner is None:
                return None
            source_id, kind = owner[2], owner[1]
            row = trades[source_id] if kind == 'TRADE' else cash[source_id]
            value = dict(activity)
            if kind == 'TRADE':
                value.update(quantity=abs(accounting.financial_decimal(row['quantity'])),
                    unitPrice=accounting.financial_decimal(row['price']),
                    fee=-accounting.financial_decimal(row['totalFeesInBaseCurrency']) * accounting.financial_decimal(row['fxRate']))
            elif kind == 'DIVIDEND':
                value.update(quantity=1, unitPrice=accounting.financial_decimal(row['change']),
                    fee=-accounting.financial_decimal(dividends[source_id]['change']))
            elif kind == 'FEE':
                value.update(quantity=1, unitPrice=0, fee=-accounting.financial_decimal(row['change']))
            else:
                value.update(quantity=1, unitPrice=accounting.financial_decimal(row['change']), fee=0)
            result.append(value)
        return result
    except (KeyError, TypeError, ValueError, RuntimeError):
        return None


def snapshot_reconciliation(snapshot: dict[str, Any], existing: dict[str, Any],
        target: str, mapping: dict[str, str], quotes: dict[str, str]) -> list[dict[str, Any]]:
    """Observe the existing read phase; incomplete evidence stays unavailable."""
    from ghostfolio_degiro_sync import accounting
    expected = exact_source_activities(snapshot, target, mapping, quotes)
    exact_body = exact_json(existing.get('_diagnostic_wire'))
    observed = []
    body = exact_body if isinstance(exact_body, dict) else existing
    for row in body.get('activities', []):
        profile = row.get('assetProfile') if 'assetProfile' in row else row.get('SymbolProfile')
        observed.append({**row, 'symbol': (profile or {}).get('symbol'),
            'dataSource': (profile or {}).get('dataSource')})
    exact = expected is not None and isinstance(exact_body, dict) and (
        exact_body.get('count') == len(observed) == len(existing.get('activities', []))
        and all(all(raw.get(field) == parsed.get(field) for field in
            ('id', 'accountId', 'type', 'comment', 'date'))
            for raw, parsed in zip(observed, existing.get('activities', []), strict=True)))
    if expected is None:
        try:
            expected = accounting.normalize_trades(snapshot, target, mapping, quotes)
            expected += accounting.normalize_dividends(snapshot, target, mapping, quotes)
            expected += accounting.normalize_fees(snapshot, target)
            expected += accounting.normalize_cash_yield(snapshot, target)
        except (RuntimeError, KeyError, TypeError, ValueError):
            # Historical report limits must not invalidate the selected interval.
            findings = reconcile_activities([], observed, snapshot.get('from_date'), snapshot.get('to_date'), exact=False)
            findings.append({'identity': None, 'status': 'uncertain', 'expected': None,
                'observed': None, 'observed_ids': [], 'source_count':
                    len(snapshot.get('transactions', [])) + len(snapshot.get('cash_movements', [])),
                'target': None, 'checks': {}, 'security_quantity': None,
                'reason': 'Source normalization unavailable', 'exact': False})
            return findings
    return reconcile_activities(expected, observed, snapshot.get('from_date'), snapshot.get('to_date'), exact=exact)


def display_value(value: object) -> str:
    """One plain line without Python representations or injected control lines."""
    if value is None:
        return 'unavailable'
    return ''.join(character if character.isprintable() else ' ' for character in str(value))


def display_number(value: object, currency: object=None) -> str:
    from ghostfolio_degiro_sync import accounting
    try:
        number = accounting.financial_decimal(value)
        if currency is not None:
            if currency not in accounting.CURRENCY_QUANTA:
                return 'unavailable'
            number = number.quantize(accounting.CURRENCY_QUANTA[currency])
        return format(number, 'f')
    except (RuntimeError, ArithmeticError):
        return 'unavailable'


def render_reconciliation(findings: list[dict[str, Any]]) -> str:
    """Plain DEGIRO report; inspection actions never authorize a mutation."""
    lines = ['DEGIRO reconciliation: nothing written']
    if not findings:
        return '\n'.join([*lines, 'No source or destination events available.', 'End DEGIRO reconciliation'])
    for index, block in enumerate(findings, 1):
        lines.append(f"Finding {index}: {display_value(block['status'])}")
        lines.append('Source identity: ' + display_value(block['identity']))
        lines.append('Compared activity: ' + display_value(block['target']))
        for label, name in (('Expected', 'expected'), ('Observed', 'observed')):
            row = block[name] or {}
            currency = row.get('currency')
            lines.append(f"{label}: type {display_value(row.get('type'))}; date {display_value(row.get('date'))}; "
                f"symbol {display_value(row.get('symbol'))}; currency {display_value(currency)}; "
                f"quantity {display_number(row.get('quantity'))}; unitPrice {display_number(row.get('unitPrice'), currency or '?')} "
                f"{display_value(currency)}; fee {display_number(row.get('fee'), currency or '?')} {display_value(currency)}")
        lines.append('Security quantity: ' + display_number(block['security_quantity']))
        lines.append('Checks: ' + ('; '.join(f'{name} {value}' for name, value in block['checks'].items()) or 'unavailable'))
        lines.append('Coverage: source events ' + str(block['source_count']) + '; destination activities '
            + str(len(block['observed_ids'])) + '; exact original decimals ' + ('yes' if block['exact'] else 'no'))
        lines.append('Reason: ' + display_value(block['reason']))
        target = block['target']
        if block['status'] == 'coherent' and target is not None:
            action = f'No action needed for activity {display_value(target)}.'
        elif block['status'] == 'to-check' and target is not None:
            action = f'Inspect activity {display_value(target)}.'
        elif block['status'] == 'outside-window':
            action = 'Retain outside-window history; no activity selected.'
        else:
            action = 'Inspect evidence; no activity selected.'
        lines.append('Action: ' + action)
    lines.append('End DEGIRO reconciliation')
    return '\n'.join(lines)


def emit_lab_evidence(kind: str, value: object) -> None:
    """Use the pinned JSON grammar once through the adapter's own logger."""
    import ghostfolio_core as core
    previous = core.log
    try:
        core.log = log
        core.log_lab_evidence(kind, value)
    finally:
        core.log = previous


def emit_window_evidence(snapshot: dict[str, Any]) -> None:
    from datetime import date
    try:
        start, end = snapshot.get('from_date'), snapshot.get('to_date')
        if not isinstance(start, str) or not isinstance(end, str) or date.fromisoformat(start) > date.fromisoformat(end):
            return
        emit_lab_evidence('window', {'from_date': start, 'to_date': end, 'timezone': 'Europe/Zurich'})
    except ValueError:
        return
