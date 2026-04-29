"""Lobby-level operations: list/create/claim/release tables.

Thin facade over :mod:`tables` with input validation and lobby-specific
serialization for the public table list.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from . import tables
from .seats import Seat
from .state import Table, TableMode


_NAME_MAX = 24
_NAME_RE = re.compile(r"\s+")


def _sanitize_name(raw: Optional[str], default: str = "Guest") -> str:
    if not raw:
        return default
    s = _NAME_RE.sub(" ", str(raw).strip())[:_NAME_MAX]
    return s or default


def _sanitize_client_id(raw: Optional[str]) -> str:
    if raw and isinstance(raw, str) and 8 <= len(raw) <= 128:
        return raw
    return str(uuid.uuid4())


async def list_lobby() -> list[dict]:
    """Public lobby listing, newest first.

    A ``with_bots`` table that has reached ``complete`` and has no humans
    is dropped; otherwise we leave it for spectators / the host to start
    a new deal.
    """
    items = tables.list_public_tables()
    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return items


async def create_table(
    mode: TableMode,
    host_client_id: Optional[str],
    host_display_name: Optional[str],
    host_seat: Optional[Seat] = None,
    min_humans: Optional[int] = None,
    public: bool = True,
    seed: Optional[int] = None,
) -> tuple[Table, Optional[str]]:
    if mode not in ("with_bots", "humans_only"):
        raise ValueError(f"unknown mode {mode!r}")
    # humans_only is by definition all-humans-no-bots; force min_humans=4
    if mode == "humans_only":
        min_humans = 4
    if min_humans is None:
        min_humans = 1
    min_humans = int(min_humans)
    if min_humans < 1 or min_humans > 4:
        raise ValueError("min_humans must be between 1 and 4")
    return await tables.create_table_full(
        mode=mode,
        host_client_id=_sanitize_client_id(host_client_id),
        host_display_name=_sanitize_name(host_display_name),
        host_seat=host_seat,
        min_humans=min_humans,
        public=public,
        seed=seed,
    )


async def claim_seat(
    table_id: str,
    seat: Seat,
    client_id: Optional[str],
    display_name: Optional[str],
) -> str:
    return await tables.claim_seat(
        table_id,
        seat,
        _sanitize_client_id(client_id),
        _sanitize_name(display_name),
    )


async def release_seat(table_id: str, token: str) -> Seat | None:
    return await tables.release_seat(table_id, token)
