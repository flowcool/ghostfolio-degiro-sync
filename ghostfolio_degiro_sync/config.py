"""Validate external configuration before constructing immutable records."""

import os
import re
from collections.abc import Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ghostfolio_degiro_sync import accounting as accounting_module
from ghostfolio_degiro_sync import diagnostics as diagnostics_module
from ghostfolio_degiro_sync import identity as identity_module
from ghostfolio_degiro_sync.models import Settings


def optional_string(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is not None and not isinstance(value, str):
        raise RuntimeError("Invalid Ghostfolio sync environment")
    return value


def required_string(values: Mapping[str, object], key: str) -> str:
    value = optional_string(values, key)
    if value is None or not value.strip():
        raise RuntimeError("Invalid Ghostfolio sync environment")
    return value


def parse_settings(values: Mapping[str, object]) -> Settings:
    host = validate_ghost_host(values.get("ghost_host"))
    token = optional_string(values, "ghost_token")
    access = optional_string(values, "ghost_access_token")
    token = token if token and token.strip() else None
    access = access if access and access.strip() else None
    if (token is None) == (access is None):
        raise RuntimeError("Set exactly one of GHOST_TOKEN or GHOST_ACCESS_TOKEN")
    if token is not None and ("\r" in token or "\n" in token):
        raise RuntimeError("Invalid Ghostfolio sync environment")
    source = required_string(values, "source_account")
    target = required_string(values, "target_account")
    mode = required_string(values, "sync_mode")
    dry_run = values.get("dry_run")
    digest = optional_string(values, "cutover_sha256")
    if (not re.fullmatch(r"[1-9][0-9]*", source)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", target)
            or mode not in ("rolling", "prospective", "full_history")
            or not isinstance(dry_run, bool)
            or (digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest))):
        raise RuntimeError("Invalid Ghostfolio sync environment")
    return Settings(ghost_host=host, ghost_token=token, ghost_access_token=access,
        source_account=source, target_account=target, dry_run=dry_run, sync_mode=mode,
        state_dir=optional_string(values, "state_dir"),
        cutover_manifest=optional_string(values, "cutover_manifest"), cutover_sha256=digest)


def runtime_config(settings: Settings) -> dict[str, object]:
    """Preserve the mutable execution format during staged module extraction."""
    result: dict[str, object] = {
        "ghost_host": settings.ghost_host, "ghost_token": settings.ghost_token,
        "source_account": settings.source_account, "target_account": settings.target_account,
        "dry_run": settings.dry_run, "sync_mode": settings.sync_mode,
        "state_dir": settings.state_dir, "cutover_manifest": settings.cutover_manifest,
        "cutover_sha256": settings.cutover_sha256}
    if settings.ghost_access_token is not None:
        result["ghost_access_token"] = settings.ghost_access_token
    return result


def validate_ghost_host(host: object) -> str:
    """Configured HTTPS origin or private HTTP; never disclose a rejected URL."""
    try:
        if not isinstance(host, str) or not host or host != host.strip():
            raise ValueError
        parts = urlsplit(host)
        name = parts.hostname
        if (parts.scheme not in ("http", "https") or not name
                or parts.username is not None or parts.password is not None
                or parts.path or parts.query or parts.fragment
                or host != f"{parts.scheme}://{parts.netloc}"
                or parts.netloc != parts.netloc.lower()
                or any(ord(char) <= 32 or ord(char) >= 127 for char in host)
                or "\\" in host or "%" in host or "?" in host or "#" in host
                or (parts.port is not None and not 1 <= parts.port <= 65535)
                or parts.netloc.endswith(":")):
            raise ValueError
        try:
            address = ip_address(name)
        except ValueError:
            address = None
            if len(name) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name):
                raise ValueError from None
            if any(not label or len(label) > 63 or label.startswith("-")
                   or label.endswith("-") for label in name.split(".")):
                raise ValueError from None
        if address is not None:
            if address.is_unspecified or address.is_multicast or address.is_link_local:
                raise ValueError
            private = address.is_loopback or (address.is_private and not address.is_reserved)
        else:
            private = "." not in name and bool(re.search(r"[a-z]", name))
        if parts.scheme == "http" and not private:
            raise ValueError
        return host
    except (ValueError, TypeError):
        raise RuntimeError("Ghostfolio target URL is outside the approved origin policy") from None


def load_ghost_credentials() -> Any:
    """Exactly one environment credential; blank inputs count as absent."""
    host = validate_ghost_host(os.environ.get("GHOST_HOST"))
    token = os.environ.get("GHOST_TOKEN")
    access = os.environ.get("GHOST_ACCESS_TOKEN")
    token = token if token and token.strip() else None
    access = access if access and access.strip() else None
    if (token is None) == (access is None):
        raise RuntimeError("Set exactly one of GHOST_TOKEN or GHOST_ACCESS_TOKEN")
    if token is not None:
        if "\r" in token or "\n" in token:
            raise RuntimeError("Invalid Ghostfolio sync environment")
        return {"ghost_host": host, "ghost_token": token}
    return {"ghost_host": host, "ghost_token": None, "ghost_access_token": access}


def verified_mapping_document(document: Any) -> Any:
    """One mapping contract shared by runtime and offline cutover preparation."""
    try:
        if not isinstance(document, dict) or not document:
            raise ValueError
        mapping: dict[str, str] = {}
        quotes: dict[str, str] = {}
        for isin, entry in document.items():
            if (not accounting_module.valid_isin(isin) or not isinstance(entry, dict)
                    or set(entry) != {"symbol", "currency"}
                    or not isinstance(entry["symbol"], str) or not entry["symbol"].strip()
                    or entry["symbol"] != entry["symbol"].strip()
                    or entry["currency"] not in accounting_module.CURRENCY_QUANTA):
                raise ValueError
            symbol, currency = entry["symbol"], entry["currency"]
            if symbol in quotes and quotes[symbol] != currency:
                raise ValueError
            mapping[isin], quotes[symbol] = symbol, currency
        return mapping, quotes
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("Invalid explicitly verified Yahoo mapping file") from None


def load_sync_config() -> Any:
    """Operator configuration only; credentials are read verbatim from environment."""
    dry_run, unused_forced = simulation_policy(os.environ)
    sync_mode = os.environ.get("SYNC_MODE")
    if sync_mode is None or not sync_mode.strip():
        raise diagnostics_module.tag_failure(RuntimeError("Set SYNC_MODE explicitly: rolling, prospective or full_history"),
                          "config", "sync_mode")
    if sync_mode not in ("full_history", "prospective", "rolling"):
        raise diagnostics_module.tag_failure(RuntimeError("Invalid synchronization mode"), "config", "sync_mode")
    with diagnostics_module.diagnostic_boundary("config", "ghostfolio_credentials"):
        credentials = load_ghost_credentials()
    target = os.environ.get("GHOST_ACCOUNT_ID")
    with diagnostics_module.diagnostic_boundary("config", "account"):
        source = identity_module.broker_identity(os.environ.get("DEGIRO_ACCOUNT_ID"))
    if (not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", target)
):
        raise diagnostics_module.tag_failure(RuntimeError("Invalid Ghostfolio sync environment"), "config", "account")
    try:
        document = yaml.safe_load(Path(os.environ.get("MAPPING_FILE", "mapping.yaml")).read_text())
        with diagnostics_module.diagnostic_boundary("config", "mapping"):
            mapping, quotes = verified_mapping_document(document)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise diagnostics_module.tag_failure(RuntimeError("Invalid explicitly verified Yahoo mapping file"),
                          "config", "mapping") from None
    return runtime_config(parse_settings({**credentials, "source_account": source,
            "target_account": target, "dry_run": dry_run,
            "state_dir": os.environ.get("STATE_DIR"), "sync_mode": sync_mode,
            "cutover_manifest": os.environ.get("CUTOVER_MANIFEST"),
            "cutover_sha256": os.environ.get("CUTOVER_SHA256")})), mapping, quotes


def valid_timezone(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def simulation_policy(values: Mapping[str, str]) -> tuple[bool, bool]:
    """Return effective simulation and explicit-live forced-preview status."""
    mode = values.get("DRY_RUN", "").strip().lower()
    if mode not in ("", "1", "true", "yes", "on", "0", "false", "no", "off"):
        raise diagnostics_module.tag_failure(RuntimeError("Invalid DRY_RUN"), "config", "account")
    requested_live = mode in ("0", "false", "no", "off")
    forced = requested_live and not valid_timezone(values.get("TZ"))
    return not requested_live or forced, forced
