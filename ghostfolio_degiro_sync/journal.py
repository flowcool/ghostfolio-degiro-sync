"""Journal operations; explicit functional boundaries."""

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

import ghostfolio_core as core
from ghostfolio_degiro_sync import accounting as accounting_module
from ghostfolio_degiro_sync import config as config_module
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import ghostfolio as ghostfolio_module
from ghostfolio_degiro_sync import identity as identity_module


def write_journal(journal: Any) -> Any:
    """Replace private state atomically, flushing both file and directory."""
    content = yaml.safe_dump(journal["document"], sort_keys=True)
    if len(content.encode("utf-8")) > 1_000_000:
        raise RuntimeError("Synchronization journal exceeds state budget")
    descriptor, temporary = tempfile.mkstemp(dir=journal["directory"], prefix=".intent-")
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, journal["path"])
        descriptor = os.open(journal["directory"], os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_state_file(descriptor: Any) -> Any:
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise RuntimeError("Unsafe private sync state file")


@contextmanager
def account_journal(config: Any) -> Iterator[Any]:
    """Hold one private account lock; unresolved requests survive process exit."""
    directory = config.get("state_dir")
    if not isinstance(directory, str) or not directory:
        raise RuntimeError("Live synchronization requires private STATE_DIR")
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise RuntimeError("Unsafe private STATE_DIR")
    owner = {"host": config_module.validate_ghost_host(config.get("ghost_host")),
             "source": identity_module.broker_identity(config.get("source_account")), "target": config.get("target_account")}
    if not isinstance(owner["target"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", owner["target"]):
        raise RuntimeError("Invalid journal account ownership")
    # Serialize by destination even if a second broker source is misconfigured.
    key = hashlib.sha256(json.dumps({"host": owner["host"], "target": owner["target"]},
        sort_keys=True).encode()).hexdigest()
    descriptor = os.open(directory / (key + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_state_file(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another synchronization owns this account") from None
        path = directory / (key + ".yaml")
        try:
            reader = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            document = {"version": 1, "owner": owner, "pending": None, "resolved": {}}
        else:
            with os.fdopen(reader) as source:
                private_state_file(source.fileno())
                if os.fstat(source.fileno()).st_size > 1_000_000:
                    raise RuntimeError("Synchronization journal exceeds state budget")
                document = yaml.safe_load(source.read())
            if (not isinstance(document, dict) or not {"version", "owner", "pending", "resolved"} <= set(document)
                    or set(document) - {"version", "owner", "pending", "resolved", "coverage"}
                    or type(document["version"]) is not int or document["version"] != 1
                    or document["owner"] != owner or not isinstance(document["resolved"], dict)
                    or document["pending"] is not None and not isinstance(document["pending"], dict)):
                raise RuntimeError("Invalid private synchronization journal")
            if "coverage" in document:
                try:
                    coverage = document["coverage"]
                    if (not isinstance(coverage, dict) or set(coverage) != {"from_date", "through"}
                            or date.fromisoformat(coverage["from_date"]) >
                            accounting_module.prospective_instant(coverage["through"]).astimezone(ZoneInfo("Europe/Zurich")).date()):
                        raise ValueError
                except (ValueError, TypeError, KeyError):
                    raise RuntimeError("Invalid rolling coverage state") from None
        yield {"directory": directory, "path": path, "document": document}
    finally:
        os.close(descriptor)


def begin_intent(journal: Any, kind: Any, payload: Any) -> Any:
    if journal["document"]["pending"] is not None:
        raise RuntimeError("Unresolved durable write intent blocks account writes")
    identity = uuid.uuid4().hex
    journal["document"]["pending"] = {"id": identity, "kind": kind, "payload": payload}
    write_journal(journal)
    return identity


def confirm_intent(journal: Any, identity: Any) -> Any:
    pending = journal["document"]["pending"]
    if not isinstance(pending, dict) or pending.get("id") != identity:
        raise RuntimeError("Synchronization intent identity changed")
    resolved = journal["document"]["resolved"]
    resolved[identity] = {"kind": pending["kind"],
        "at": datetime.now(UTC).isoformat()}
    if len(resolved) > 1000:
        # Only confirmed audit metadata ages out; pending intent is never pruned.
        keep = sorted(resolved.items(), key=lambda item: (accounting_module.broker_instant(item[1]["at"]), item[0]))[-1000:]
        journal["document"]["resolved"] = dict(keep)
    journal["document"]["pending"] = None
    write_journal(journal)


def selected_import_intent(journal: Any, expected_intent_id: Any) -> Any:
    """Select a specific import under its owner lock before obtaining evidence."""
    if (not isinstance(expected_intent_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", expected_intent_id)):
        raise RuntimeError("Invalid expected synchronization intent identity")
    pending = journal["document"]["pending"]
    if (not isinstance(pending, dict) or pending.get("kind") != "import"
            or not isinstance(pending.get("payload"), dict) or not pending["payload"]):
        raise RuntimeError("No recoverable pending import intent")
    if pending.get("id") != expected_intent_id:
        raise RuntimeError("Synchronization intent identity changed")
    return pending


def verify_import_intent(journal: Any, config: Any, existing_body: Any, expected_intent_id: Any) -> Any:
    pending = selected_import_intent(journal, expected_intent_id)
    target = {"id": config["target_account"]}
    rows, _ = ghostfolio_module.existing_activity_context(existing_body, target)
    candidates = list(pending["payload"].values())
    if (any(not isinstance(row, dict) or row.get("comment") != identity
            for identity, row in pending["payload"].items())
            or ghostfolio_module.pending_activities(candidates, rows, target, config["source_account"])):
        raise RuntimeError("Complete exact positive readback required for recovery")
    return len(candidates)


def resolve_import_intent(config: Any, existing_body: Any, *, expected_intent_id: Any) -> Any:
    """Resolve one explicitly selected request using complete positive readback."""
    with account_journal(config) as journal:
        matched = verify_import_intent(journal, config, existing_body, expected_intent_id)
        confirm_intent(journal, expected_intent_id)
        return matched


def readback_import_intent(config: Any, *, expected_intent_id: Any, confirm: Any=False) -> Any:
    """Optional login then financial GET-only recovery; explicit confirmation."""
    if type(confirm) is not bool:
        raise RuntimeError("Invalid local recovery confirmation mode")
    readonly = {**config, "dry_run": True}
    with account_journal(readonly) as journal:
        selected_import_intent(journal, expected_intent_id)
        ghostfolio_module.authenticate_ghostfolio(readonly)
        target = {"id": readonly["target_account"]}
        with ghostfolio_module.ghost_transport(readonly, target) as session:
            response = session.get(f"{readonly['ghost_host']}/api/v1/account/{target['id']}")
            if response.status_code != 200:
                raise RuntimeError("Recovery account readback failed")
            current = response.json()
            if (not isinstance(current, dict) or current.get("id") != target["id"]
                    or not core.activity_is_active({"account": current})
                    or current.get("currency") not in accounting_module.CURRENCY_QUANTA
                    or current.get("balance") is None):
                raise RuntimeError("Invalid or redacted recovery account context")
            accounting_module.financial_decimal(current["balance"])
            response = session.get(f"{readonly['ghost_host']}/api/v1/activities")
            if response.status_code != 200:
                raise RuntimeError("Recovery activity readback failed")
            body = response.json()
        matched = verify_import_intent(journal, readonly, body, expected_intent_id)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if confirm:
            confirm_intent(journal, expected_intent_id)
        return {"matched": matched, "confirmed": confirm, "snapshot_sha256": digest}


def evidence_digest(value: Any) -> Any:
    """Stable JSON evidence digest; reject non-finite or unrepresentable input."""
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError):
        raise RuntimeError("Invalid prospective evidence content") from None


def read_private_evidence(path: Any, expected_digest: Any) -> Any:
    """Read bounded, owned regular evidence without following a final symlink."""
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise RuntimeError("Missing prospective evidence digest")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 2_000_000):
            raise RuntimeError("Unsafe prospective evidence file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read(2_000_001)
        if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != expected_digest:
            raise RuntimeError("Changed prospective evidence file")
        return content
    except (OSError, TypeError):
        raise RuntimeError("Unavailable prospective evidence file") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def unique_evidence_pairs(pairs: Any) -> Any:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("Duplicate prospective evidence key")
        result[key] = value
    return result


def load_prospective_evidence(path: Any, expected_digest: Any) -> Any:
    """An operator-pinned YAML manifest binds two unchanged private JSON captures."""
    try:
        content = read_private_evidence(path, expected_digest)
        # Inspect mapping nodes before safe_load: duplicate keys are never last-wins.
        root = yaml.compose(content)
        pending, visited = [root], set()
        while pending:
            node = pending.pop()
            if node is None or id(node) in visited:
                raise RuntimeError("Aliased prospective manifest is unsupported")
            visited.add(id(node))
            if isinstance(node, yaml.MappingNode):
                keys = [key.value for key, unused in node.value]
                if len(keys) != len(set(keys)):
                    raise RuntimeError("Duplicate prospective evidence key")
                pending.extend(item for pair in node.value for item in pair)
            elif isinstance(node, yaml.SequenceNode):
                pending.extend(node.value)
        manifest = yaml.safe_load(content)
        if (not isinstance(manifest, dict) or set(manifest) != {
                "version", "source_account", "target_account", "cutover",
                "mapping_sha256", "opening", "basis_status"}
                or type(manifest["version"]) is not int or manifest["version"] != 1
                or manifest["basis_status"] != "unverified"
                or set(manifest["opening"]) != {"broker", "destination"}):
            raise RuntimeError("Invalid prospective manifest schema")
        captures = {}
        for name, binding in manifest["opening"].items():
            if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
                raise RuntimeError("Invalid prospective capture binding")
            location = Path(binding["path"])
            if not location.is_absolute():
                location = Path(path).parent / location
            captures[name] = json.loads(read_private_evidence(location, binding["sha256"]),
                object_pairs_hook=unique_evidence_pairs,
                parse_constant=lambda unused: (_ for _ in ()).throw(
                    RuntimeError("Non-finite prospective evidence")))
        return {"manifest": manifest, "captures": captures,
                "manifest_sha256": expected_digest}
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError, yaml.YAMLError):
        raise RuntimeError("Malformed prospective evidence") from None


def recover_confirmed_import(journal: Any, config: Any, existing_body: Any) -> Any:
    """Never infer non-delivery: clear only complete exact positive readback."""
    if type(config.get("dry_run", True)) is not bool:
        raise RuntimeError("Invalid DRY_RUN flag")
    pending = journal["document"]["pending"]
    if pending is None:
        return
    if pending.get("kind") != "import":
        raise RuntimeError("Unresolved durable write intent blocks account writes")
    verify_import_intent(journal, config, existing_body, pending["id"])
    if not config.get("dry_run", True):
        confirm_intent(journal, pending["id"])
        config.get("_uncertain_import_accounts", set()).discard(config["target_account"])
    diagnostics_module.log.info("Interrupted import confirmed by complete exact readback%s",
             "; DRY_RUN preserves journal" if config.get("dry_run", True) else "")
