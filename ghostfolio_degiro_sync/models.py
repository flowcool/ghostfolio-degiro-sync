"""Immutable records; business operations remain module-level functions."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    ghost_host: str
    ghost_token: str | None = field(repr=False)
    ghost_access_token: str | None = field(repr=False)
    source_account: str
    target_account: str
    dry_run: bool
    sync_mode: str
    state_dir: str | None
    cutover_manifest: str | None
    cutover_sha256: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionResult:
    proposals: tuple[Mapping[str, object], ...]
    rejected: tuple[str, ...]
    deferred: tuple[str, ...]
    holdings: tuple[tuple[str, str, Decimal], ...]
