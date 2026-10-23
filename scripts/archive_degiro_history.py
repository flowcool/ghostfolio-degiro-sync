#!/usr/bin/env python3
"""Retain private DEGIRO source responses. Archives never authorize imports."""
import argparse
import csv
import io
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import stat
from urllib.parse import urlsplit
from uuid import uuid4

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghostfolio_degiro_sync import config, degiro, vault
from ghostfolio_degiro_sync.app import redact_auth_fields
from ghostfolio_degiro_sync.diagnostics import private_broker_logs


MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_PRODUCT_IDS = 10000
MAX_PRODUCT_REQUESTS = 100
MAX_JSON_DEPTH = 64
PATHS = {
    "transactions": "/portfolio-reports/secure/v4/transactions",
    "account_overview": "/portfolio-reports/secure/v6/accountoverview",
    "products": "/product_search/secure/v5/products/info",
    "account_info": r"/trading/secure/v5/account/info/[0-9]+;jsessionid=[^/]+",
    "account_update": r"/trading/secure/v5/update/[0-9]+;jsessionid=[^/]+",
    "account_report": "/portfolio-reports/secure/v3/cashAccountReport/csv",
}


def preflight(args):
    start, end = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
    windows = degiro.history_windows(start, end, args.window_days)
    if not config.simulation_policy(os.environ)[0]:
        raise RuntimeError("simulation_required")
    locale = (args.report_country, args.report_language)
    if any(locale) and not all(isinstance(part, str) and re.fullmatch(r"[a-z]{2}", part) for part in locale):
        raise RuntimeError("invalid_locale")
    return windows, locale if all(locale) else None


def now():
    return datetime.now(UTC).isoformat()


def private_directory(output):
    """Open every ancestor without following symlinks; anchor all later writes."""
    path = Path(os.path.abspath(output))
    package = Path(degiro.__file__).resolve().parent
    script = Path(__file__).resolve()
    root = script.parents[1]
    if path == script or path in script.parents or path == package or path in package.parents or package in path.parents:
        raise RuntimeError("input_output_overlap")
    if (root / ".git").exists() and path.is_relative_to(root) and not path.is_relative_to(root / "tmp"):
        raise RuntimeError("private_output_in_repository")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        os.mkdir(path.name, mode=0o700, dir_fd=fd)
        result = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            os.fchmod(result, 0o700)
            os.fsync(fd)
            return result
        except BaseException:
            os.close(result)
            raise
    finally:
        os.close(fd)


def publish(fd, name, body, replace=False):
    """Durable private staging. Responses use no-replace publication."""
    temporary = ".pending-" + uuid4().hex
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    else:
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.unlink(temporary, dir_fd=fd)
    os.fsync(fd)


def save_index(fd, index):
    publish(fd, "index.yaml", yaml.safe_dump(index, sort_keys=False).encode("utf-8"), replace=True)


def sensitive_key(key):
    # Reuse the exact snapshot vocabulary, including case and substring semantics.
    return not redact_auth_fields({key: None})


def eligible_body(raw, csv, sensitive_values, one_time_values=()):
    """Inspect all JSON key occurrences before duplicate keys can collapse."""
    try:
        text = raw.decode("utf-8-sig" if csv else "utf-8")
    except UnicodeError:
        raise RuntimeError("invalid_encoding") from None
    # OTP digits can occur inside valid identifiers and high-precision amounts.
    # Only OTPs use token boundaries; long-lived secrets keep substring checks.
    one_time_pattern = (re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(value) for value in one_time_values)
                                   + r")(?![\w.])") if one_time_values else None)
    if any(value in text for value in sensitive_values) or (one_time_pattern and one_time_pattern.search(text)):
        raise RuntimeError("credential_material")
    if csv:
        if re.search(r"token|session|password|username|otp|secret", text, re.IGNORECASE):
            raise RuntimeError("credential_material")
        return None
    # Inspect every string, including overwritten duplicate values and escaped keys.
    # Count nesting before parsing, including branches later hidden by duplicates.
    position, depth = 0, 0
    tokens = re.compile(r'["{}\[\]]')
    while match := tokens.search(text, position):
        token = match.group()
        position = match.end()
        if token == '"':
            try:
                value, position = json.decoder.scanstring(text, position)
            except ValueError:
                raise RuntimeError("unparseable_json") from None
            if any(secret in value for secret in sensitive_values) or (one_time_pattern and one_time_pattern.search(value)):
                raise RuntimeError("credential_material")
        elif token in "{[":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise RuntimeError("json_depth_limit")
        else:
            depth -= 1

    def pairs(items):
        if any(sensitive_key(key) for key, value in items):
            raise RuntimeError("credential_key")
        return dict(items)

    def invalid_constant(value):
        raise ValueError("non_json_number")

    try:
        data = json.loads(text, object_pairs_hook=pairs, parse_float=str,
                          parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise RuntimeError("unparseable_json") from None
    return data


def product_ids(data, step, identities):
    """Only inspect already-published source. Bad identifiers do not erase rows."""
    pending = [data]
    # Portfolio entries refer to products by their outer id, unlike history rows.
    if step["kind"] == "account_update" and isinstance(data, dict):
        portfolio = data.get("portfolio")
        rows = portfolio.get("value") if isinstance(portfolio, dict) else None
        if isinstance(rows, list):
            pending.extend({"productId": row["id"]} for row in rows if isinstance(row, dict) and "id" in row)
    step["invalid_product_ids_skipped"] = 0
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if "productId" in value:
                identity = value["productId"]
                try:
                    parsed = int(identity) if type(identity) in (int, str) and re.fullmatch(r"[0-9]+", str(identity)) else 0
                except ValueError:
                    parsed = 0
                if parsed <= 0:
                    step["invalid_product_ids_skipped"] += 1
                else:
                    identities.add(parsed)
                    if len(identities) > MAX_PRODUCT_IDS:
                        raise RuntimeError("product_id_limit")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def capture(windows, locale, fd, index):
    from degiro_connector.trading.actions.action_connect import ActionConnect
    from degiro_connector.trading.actions.action_get_client_details import ActionGetClientDetails
    from degiro_connector.trading.actions.action_get_transactions_history import ActionGetTransactionsHistory
    from degiro_connector.trading.actions.action_get_account_overview import ActionGetAccountOverview
    from degiro_connector.trading.actions.action_get_account_info import ActionGetAccountInfo
    from degiro_connector.trading.actions.action_get_update import ActionGetUpdate
    from degiro_connector.trading.actions.action_get_products_info import ActionGetProductsInfo
    from degiro_connector.trading.actions.action_get_account_report import ActionGetAccountReport
    from degiro_connector.trading.actions.action_logout import ActionLogout
    from degiro_connector.trading.models.account import OverviewRequest, ReportRequest, UpdateOption, UpdateRequest
    from degiro_connector.trading.models.transaction import HistoryRequest

    index["stage"] = "vault"
    save_index(fd, index)
    credentials = vault.broker_credentials()
    session = degiro.bounded_broker_session()
    logger = degiro.quiet_broker_logger()
    session_id = None
    active = None
    sticky_failure = None
    retained = 0
    identities = set()
    sensitive_values = {str(value) for value in (credentials.username, credentials.password,
        credentials.totp_secret_key, credentials.in_app_token) if value is not None}
    one_time_values = ({str(credentials.one_time_password)} if credentials.one_time_password is not None else set())
    sensitive_values.update(os.environ[name] for name in (
        "BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD", "BW_SESSION", "GHOST_TOKEN", "GHOST_ACCESS_TOKEN")
        if os.environ.get(name))
    original_send = session.send
    control = "login"
    control_requests = set()
    control_paths = {"login": r"/login/secure/login/totp", "client_discovery": r"/pa/secure/client",
                     "logout": r"/trading/secure/logout;jsessionid=[^/]+"}

    def response_hook(response, **kwargs):
        nonlocal sticky_failure, retained
        if active is None:
            return response
        try:
            active["responses_seen"] += 1
            active["http_status"] = response.status_code
            raw = response.content  # HTTP-decoded bytes; existing transport buffers in memory.
            active.update(byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest(), fetched_at=now())
            if not 200 <= response.status_code < 300:
                raise RuntimeError("http_failure")
            if len(raw) > MAX_BODY_BYTES:
                raise RuntimeError("body_byte_limit")
            if retained + len(raw) > MAX_TOTAL_BYTES:
                raise RuntimeError("total_byte_limit")
            data = eligible_body(raw, active["kind"] == "account_report", sensitive_values, one_time_values)
            name = active["id"] + (".csv" if active["kind"] == "account_report" else ".json")
            publish(fd, name, raw)
            retained += len(raw)
            active.update(file=name, status="retained")
            # Publication precedes both extraction here and interpretation by the vendor.
            index["retained_bytes"] = retained
            if active["kind"] != "products":
                product_ids(data, active, identities)
            save_index(fd, index)
        except Exception as error:
            allowed = {"invalid_encoding", "credential_material", "credential_key", "unparseable_json",
                       "json_depth_limit", "http_failure", "body_byte_limit", "total_byte_limit", "product_id_limit"}
            reason = str(error) if type(error) is RuntimeError and str(error) in allowed else "archive_storage_or_transport_failure"
            sticky_failure = reason
            active.update(status="failed", refusal_reason=reason)
            raise RuntimeError("archive_response_refused") from None
        return response

    def send(request, **kwargs):
        nonlocal sticky_failure
        path = urlsplit(request.url).path
        if active is not None:
            expected_method = "POST" if active["kind"] == "products" else "GET"
            if (sticky_failure or active["requests_dispatched"] or request.method != expected_method
                    or not re.fullmatch(PATHS[active["kind"]], path)):
                sticky_failure = "unexpected_collection_request"
                raise RuntimeError("unexpected_collection_request")
            active["requests_dispatched"] = 1
        else:
            if control in control_requests or not re.fullmatch(control_paths[control], path):
                raise RuntimeError("unexpected_control_request")
            control_requests.add(control)
            # Capture generated OTP only in memory so it cannot leak into evidence.
            if control == "login":
                payload = json.loads(request.body)
                one_time_values.update(str(value) for key, value in payload.items()
                                       if key == "oneTimePassword" and value is not None)
                sensitive_values.update(str(value) for key, value in payload.items()
                                        if key != "oneTimePassword" and sensitive_key(key) and value is not None)
        try:
            return original_send(request, **kwargs)
        except Exception:
            if active is not None:
                sticky_failure = sticky_failure or "collection_transport_failure"
            raise RuntimeError("archive_request_failed") from None
        finally:
            session.degiro_evidence.clear()

    session.hooks["response"].append(response_hook)
    session.send = send

    def collect(kind, action, start=None, end=None, **kwargs):
        nonlocal active
        identity = "response-" + str(len(index["steps"]) + 1).zfill(4)
        active = {"id": identity, "kind": kind, "status": "pending", "responses_seen": 0, "requests_dispatched": 0,
                  "source_account": index["source_account"], "fetch_started_at": now()}
        if start is not None:
            active.update(from_date=start.isoformat(), to_date=end.isoformat())
        if kind == "account_report":
            active["report_locale"] = list(locale)
        if kind == "products":
            active["requested_product_ids"] = kwargs["product_list"]
        index["steps"][identity] = active
        index["stage"] = kind
        try:
            save_index(fd, index)  # Durable intent exists before any network dispatch.
            result = degiro.broker_call(action, **shared, **kwargs)
            if sticky_failure:
                raise RuntimeError("archive_failure")
            if active["responses_seen"] != 1 or active["status"] != "retained":
                raise RuntimeError("missing_collection_response")
            return result
        except Exception:
            active.update(status="failed", refusal_reason=sticky_failure or "collection_failed")
            raise RuntimeError("collection_failed") from None
        finally:
            session.degiro_evidence.clear()
            active = None

    failure = None
    with private_broker_logs():
        try:
            index["stage"] = "login"
            save_index(fd, index)
            session_id = degiro.broker_call(ActionConnect.get_session_id, credentials=credentials, session=session, logger=logger)
            if not isinstance(session_id, str) or not session_id.strip():
                raise RuntimeError("invalid_session")
            sensitive_values.add(session_id)
            shared = {"session_id": session_id, "session": session, "logger": logger}
            control = "client_discovery"
            index["stage"] = control
            save_index(fd, index)
            client = degiro.broker_call(ActionGetClientDetails.get_client_details, **shared)
            account = client.get("data", {}).get("intAccount") if isinstance(client, dict) and isinstance(client.get("data"), dict) else None
            if type(account) is not int or account <= 0:
                raise RuntimeError("invalid_source_account")
            credentials.int_account = account
            shared["credentials"] = credentials
            index["source_account"] = str(account)
            for start, end in windows:
                collect("transactions", ActionGetTransactionsHistory.get_transactions_history, start, end,
                        transaction_request=HistoryRequest(from_date=start, to_date=end, group_transactions_by_order=False), raw=True)
                collect("account_overview", ActionGetAccountOverview.get_account_overview, start, end,
                        overview_request=OverviewRequest(from_date=start, to_date=end), raw=True)
            collect("account_info", ActionGetAccountInfo.get_account_info)
            collect("account_update", ActionGetUpdate.get_update, request_list=[
                UpdateRequest(option=option, last_updated=0) for option in
                (UpdateOption.PORTFOLIO, UpdateOption.TOTAL_PORTFOLIO, UpdateOption.CASH_FUNDS)], raw=True)
            ids = sorted(identities)
            if (len(ids) + 99) // 100 > MAX_PRODUCT_REQUESTS:
                raise RuntimeError("product_request_limit")
            for offset in range(0, len(ids), 100):
                collect("products", ActionGetProductsInfo.get_products_info, product_list=ids[offset:offset + 100], raw=True)
            if locale:
                collect("account_report", ActionGetAccountReport.get_cash_account_report, windows[0][0], windows[-1][1],
                        report_request=ReportRequest(country=locale[0], lang=locale[1], from_date=windows[0][0], to_date=windows[-1][1]), raw=True)
        except Exception as error:
            failure = str(error) if type(error) is RuntimeError and str(error) in {
                "product_request_limit", "invalid_session", "invalid_source_account"} else "collection_failed"
        finally:
            control = "logout"
            if session_id:
                try:
                    if degiro.broker_call(ActionLogout.logout, credentials=credentials, session_id=session_id, session=session, logger=logger) is not True:
                        raise RuntimeError("logout_failed")
                    index["logout"] = "finished"
                except Exception:
                    index["logout"] = "failed"
                    failure = failure or "logout_failed"
            session.degiro_evidence.clear()
            session.close()
    if failure:
        index["failure_reason"] = failure
        raise RuntimeError(failure)


CLASSIFICATIONS = ("excluded_legacy", "malformed", "unknown", "unassessed")
LEGACY_TYPES = {"CASH_FUND_NAV_CHANGE", "CASH_FUND_TRANSACTION"}
CASH_TYPES = {"TRANSACTION", "CASH_TRANSACTION", "FLATEX_CASH_SWEEP", "COMPENSATION_BOOKING"}
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_STEPS = 2 * degiro.MAX_HISTORY_WINDOWS + MAX_PRODUCT_REQUESTS + 3
DUPLICATE_KEYS = object()  # Cannot collide with an external JSON string key.


def open_archive_directory(path):
    path = Path(os.path.abspath(path))
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError("unsafe_archive_directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_archive_file(fd, name, limit, expected_hash, expected_size=None):
    if (not isinstance(name, str) or not name or name in (".", "..")
            or "/" in name or "\\" in name or "\x00" in name):
        raise RuntimeError("unsafe_response_path")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("invalid_hash_binding")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise RuntimeError("unsafe_private_file")
        if info.st_size > limit:
            raise RuntimeError("file_size_limit")
        if expected_size is not None and (type(expected_size) is not int or expected_size != info.st_size):
            raise RuntimeError("size_mismatch")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise RuntimeError("file_changed_during_read")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError("hash_mismatch")
    return raw


def archive_index(raw):
    # Reject aliases and duplicate mappings before construction. The index is untrusted.
    depth = 0
    for event in yaml.parse(raw):
        if isinstance(event, yaml.events.AliasEvent):
            raise RuntimeError("index_alias_refused")
        if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise RuntimeError("index_depth_limit")
        elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
            depth -= 1
    node = yaml.compose(raw)
    pending = [node]
    while pending:
        item = pending.pop()
        if isinstance(item, yaml.nodes.MappingNode):
            keys = set()
            for key, value in item.value:
                if not isinstance(key, yaml.nodes.ScalarNode) or key.value in keys:
                    raise RuntimeError("invalid_index_mapping")
                keys.add(key.value)
                pending.append(value)
        elif isinstance(item, yaml.nodes.SequenceNode):
            pending.extend(item.value)
    index = yaml.safe_load(raw)
    if (not isinstance(index, dict) or type(index.get("version")) is not int or index["version"] != 1
            or index.get("status") not in ("pending", "failed", "requests_finished")
            or index.get("history_completeness_verified") is not False
            or index.get("import_status") != "archive_not_importable"
            or not isinstance(index.get("steps"), dict) or len(index["steps"]) > MAX_ARCHIVE_STEPS):
        raise RuntimeError("invalid_archive_index")
    return index


def diagnostic_json(raw):
    # Keep ambiguous row objects locatable. Never adopt ambiguous collections.
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                result.setdefault(DUPLICATE_KEYS, set()).add(key)
            result[key] = value
        return result
    eligible_body(raw, False, set())
    return json.loads(raw, object_pairs_hook=unique, parse_float=str)


def row_diagnostic(row, kind):
    if not isinstance(row, dict):
        return "malformed", "row_not_object", "<non_object>"
    if DUPLICATE_KEYS in row:
        return "malformed", "ambiguous_duplicate_row_keys", "<ambiguous>"
    if kind not in ("transactions", "account_overview"):
        return "unassessed", "accounting_not_assessed", "<metadata>"
    field = "buysell" if kind == "transactions" else "type"
    value = row.get(field)
    if not isinstance(value, str) or not value:
        return "malformed", "missing_or_invalid_discriminator", "<missing_or_invalid>"
    label = value if re.fullmatch(r"[A-Za-z0-9_]{1,80}", value) else "<other>"
    if value in LEGACY_TYPES:
        return "excluded_legacy", "unsupported_legacy_cash_fund_record", label
    known = {"B", "S"} if kind == "transactions" else CASH_TYPES
    if value not in known:
        return "unknown", "unrecognized_source_type", label
    return "unassessed", "accounting_not_assessed", label


def response_diagnostics(raw, kind):
    result = {"row_count": 0, "classifications": dict.fromkeys(CLASSIFICATIONS, 0),
              "type_counts": {}, "rows": [], "findings": []}

    def add(offset, row, csv_row=False, malformed=False):
        category, reason, label = (("malformed", "csv_column_count_mismatch", "<csv>") if malformed else
            ("unassessed", "csv_accounting_not_assessed", "<csv>") if csv_row else row_diagnostic(row, kind))
        result["row_count"] += 1
        result["classifications"][category] += 1
        result["type_counts"][label] = result["type_counts"].get(label, 0) + 1
        result["rows"].append({"offset": offset, "classification": category, "reason": reason})

    if kind == "account_report":
        eligible_body(raw, True, set())
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        previous_limit = csv.field_size_limit(MAX_BODY_BYTES)
        try:
            header = next(reader, None)
            if header is None:
                result["findings"].append("missing_csv_header")
                return result
            for offset, row in enumerate(reader):
                add("/csv/" + str(offset), row, csv_row=True, malformed=len(row) != len(header))
                result["rows"][-1]["physical_line_end"] = reader.line_num
        except csv.Error:
            result["findings"].append("unreadable_csv_remainder")
        finally:
            csv.field_size_limit(previous_limit)
        return result
    data = diagnostic_json(raw)
    if not isinstance(data, dict):
        result["findings"].append("malformed_response_envelope")
        return result
    collection_keys = {"portfolio", "cashFunds", "totalPortfolio"} if kind == "account_update" else {"data"}
    if data.get(DUPLICATE_KEYS, set()) & collection_keys:
        result["findings"].append("ambiguous_duplicate_json_key")
        return result
    if kind == "account_update":
        for collection in ("portfolio", "cashFunds", "totalPortfolio"):
            wrapper = data.get(collection)
            if isinstance(wrapper, dict) and "value" in wrapper.get(DUPLICATE_KEYS, set()):
                result["findings"].append("ambiguous_duplicate_" + collection)
                continue
            rows = wrapper.get("value") if isinstance(wrapper, dict) else None
            if not isinstance(rows, list):
                result["findings"].append("missing_or_malformed_" + collection)
                continue
            for offset, row in enumerate(rows):
                add("/" + collection + "/value/" + str(offset), row)
        return result
    rows = data.get("data")
    prefix = "/data"
    if isinstance(rows, dict) and ((kind == "account_overview" and "cashMovements" in rows.get(DUPLICATE_KEYS, set()))
            or (kind == "products" and DUPLICATE_KEYS in rows)):
        result["findings"].append("ambiguous_duplicate_json_key")
        return result
    if kind == "account_overview":
        rows = rows.get("cashMovements") if isinstance(rows, dict) else None
        prefix += "/cashMovements"
    if kind == "account_info":
        if isinstance(rows, dict):
            add(prefix, rows)
        else:
            result["findings"].append("missing_or_malformed_collection")
    elif kind == "products":
        if isinstance(rows, dict):
            for key, row in rows.items():
                add(prefix + "/" + key.replace("~", "~0").replace("/", "~1"), row)
        else:
            result["findings"].append("missing_or_malformed_collection")
    elif isinstance(rows, list):
        for offset, row in enumerate(rows):
            add(prefix + "/" + str(offset), row)
    else:
        result["findings"].append("missing_or_malformed_collection")
    return result


def inspect_archive(args):
    source = Path(os.path.abspath(args.inspect_directory))
    output = Path(os.path.abspath(args.output_directory))
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise RuntimeError("input_output_overlap")
    fd = open_archive_directory(source)
    try:
        raw_index = read_archive_file(fd, "index.yaml", MAX_INDEX_BYTES, args.index_sha256)
        index = archive_index(raw_index)
        report = {"version": 1, "index_sha256": args.index_sha256, "collection_status": index["status"],
                  "history_completeness_verified": False, "import_status": "archive_not_importable",
                  "financial_writes": 0, "notice": "No financial write occurred. Full-account synchronization guards still apply. No row is certified valid or reconciled.",
                  "responses": {}, "findings": [], "unindexed_files": []}
        indexed = {"index.yaml"}
        seen_files = set()
        total = 0
        for identity, step in index["steps"].items():
            if (not isinstance(identity, str) or not re.fullmatch(r"response-[0-9]{4}", identity)
                    or not isinstance(step, dict) or step.get("id") != identity
                    or step.get("kind") not in PATHS or step.get("status") not in ("pending", "failed", "retained")):
                raise RuntimeError("invalid_step_binding")
            kind = step["kind"]
            result = {"kind": kind, "collection_status": step["status"], "verification": "unavailable",
                      "row_count": 0, "classifications": dict.fromkeys(CLASSIFICATIONS, 0),
                      "type_counts": {}, "rows": [], "findings": []}
            report["responses"][identity] = result
            for field in ("from_date", "to_date"):
                if field in step:
                    if not isinstance(step[field], str) or date.fromisoformat(step[field]).isoformat() != step[field]:
                        raise RuntimeError("invalid_step_date")
                    result[field] = step[field]
            if type(step.get("http_status")) is int and 100 <= step["http_status"] <= 599:
                result["http_status"] = step["http_status"]
            if type(step.get("byte_count")) is int and step["byte_count"] >= 0:
                result["available_byte_count"] = step["byte_count"]
            if isinstance(step.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", step["sha256"]):
                result["available_sha256"] = step["sha256"]
            if step["status"] != "retained":
                result["findings"].append("pending_intent" if step["status"] == "pending" else "failed_or_refused_step")
                reasons = {"invalid_encoding", "credential_material", "credential_key", "unparseable_json",
                           "json_depth_limit", "http_failure", "body_byte_limit", "total_byte_limit",
                           "product_id_limit", "archive_storage_or_transport_failure", "collection_failed",
                           "unexpected_collection_request", "collection_transport_failure"}
                if isinstance(step.get("refusal_reason"), str) and step["refusal_reason"] in reasons:
                    result["refusal_reason"] = step["refusal_reason"]
            if "file" not in step:
                result["findings"].append("body_unavailable")
                continue
            name = step["file"]
            expected_name = identity + (".csv" if kind == "account_report" else ".json")
            if name != expected_name or name in seen_files:
                result["findings"].append("unsafe_or_duplicate_response_path")
                continue
            seen_files.add(name)
            indexed.add(name)
            try:
                size = step.get("byte_count")
                if type(size) is not int or size < 0:
                    raise RuntimeError("invalid_size_binding")
                total += size
                if total > MAX_TOTAL_BYTES:
                    raise RuntimeError("total_byte_limit")
                if step.get("responses_seen") != 1 or step.get("requests_dispatched") != 1:
                    raise RuntimeError("invalid_response_count")
                body = read_archive_file(fd, name, MAX_BODY_BYTES, step.get("sha256"), size)
                result.update(sha256=step["sha256"], byte_count=size, verification="hash_verified")
                result.update(response_diagnostics(body, kind))
            except Exception as error:
                # No untrusted paths, payloads or exception messages cross this boundary.
                codes = {"unsafe_response_path", "invalid_hash_binding", "unsafe_private_file", "file_size_limit",
                         "size_mismatch", "file_changed_during_read", "hash_mismatch", "invalid_size_binding",
                         "invalid_response_count", "total_byte_limit", "ambiguous_duplicate_json_key",
                         "credential_key", "credential_material", "json_depth_limit", "invalid_encoding", "unparseable_json"}
                reason = str(error) if type(error) is RuntimeError and str(error) in codes else "unreadable_response"
                result["findings"].append(reason)
        report["unindexed_files"] = sorted(set(os.listdir(fd)) - indexed)
        if report["unindexed_files"]:
            report["findings"].append("unindexed_files_not_adopted")
        if index["status"] != "requests_finished":
            report["findings"].append("collection_not_finished")
        report["inspection_status"] = "findings_detected" if report["findings"] or any(
            row["findings"] or row["classifications"]["excluded_legacy"] or row["classifications"]["malformed"]
            or row["classifications"]["unknown"] for row in report["responses"].values()) else "unassessed_only"
    finally:
        os.close(fd)
    output_fd = private_directory(output)
    try:
        publish(output_fd, "report.yaml", yaml.safe_dump(report, sort_keys=False).encode())
    finally:
        os.close(output_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--window-days", type=int)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--report-country")
    parser.add_argument("--report-language")
    parser.add_argument("--inspect-directory")
    parser.add_argument("--index-sha256")
    args = parser.parse_args(argv)
    try:
        if args.inspect_directory is not None:
            if not args.index_sha256 or any(value is not None for value in (
                    args.from_date, args.to_date, args.window_days, args.report_country, args.report_language)):
                raise RuntimeError("invalid_inspection_options")
            inspect_archive(args)
            print("Offline inspection finished; archive_not_importable; no financial writes")
            return 0
        if args.index_sha256 is not None or not args.from_date or not args.to_date:
            raise RuntimeError("invalid_capture_options")
        args.window_days = args.window_days if args.window_days is not None else 90
        windows, locale = preflight(args)
        fd = private_directory(args.output_directory)
        index = {"version": 1, "status": "pending", "history_completeness_verified": False,
                 "import_status": "archive_not_importable", "fetch_started_at": now(),
                 "from_date": args.from_date, "to_date": args.to_date, "window_days": args.window_days,
                 "retained_bytes": 0, "steps": {}}
        try:
            save_index(fd, index)
            capture(windows, locale, fd, index)
            index.update(status="requests_finished", fetch_finished_at=now())
            save_index(fd, index)
        except Exception:
            index.update(status="failed", fetch_finished_at=now())
            try:
                save_index(fd, index)
            except Exception:
                pass  # Earlier durable index/response files remain; never claim success.
            raise
        finally:
            os.close(fd)
    except Exception:
        print("Archive refused; no financial writes attempted", file=sys.stderr)
        return 1
    print("Archive requests finished; history unverified; archive_not_importable; no financial writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
