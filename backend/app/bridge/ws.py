"""WebSocket connection manager + per-seat broadcasting.

Each WebSocket is tagged ``(table_id, seat)``. On connect we mark the seat
connected and push the current per-seat view; on every backend mutation
the registered broadcaster fans out fresh views to every open socket
filtered through :func:`view_for`, so hidden hands stay hidden.

This module registers itself as the broadcaster for :mod:`tables` at
import time so that any state mutation in the engine results in a push
to all connected sockets without a circular import.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from . import tables
from .seats import Seat
from .views import view_for


class ConnectionManager:
    def __init__(self) -> None:
        # table_id -> seat -> set of websockets (multiple tabs allowed)
        self._conns: dict[str, dict[Seat, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self._lock = asyncio.Lock()

    async def register(self, table_id: str, seat: Seat, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[table_id][seat].add(ws)
        await tables.on_seat_connect(table_id, seat)
        # Send initial state immediately
        try:
            table = tables.get_table(table_id)
        except KeyError:
            return
        view = view_for(table, seat)
        try:
            await ws.send_json({"type": "state", "state": view, "events": []})
        except Exception:  # noqa: BLE001
            pass

    async def unregister(self, table_id: str, seat: Seat, ws: WebSocket) -> None:
        has_other = False
        async with self._lock:
            seat_conns = self._conns.get(table_id, {}).get(seat)
            if seat_conns is not None:
                seat_conns.discard(ws)
                has_other = bool(seat_conns)
        await tables.on_seat_disconnect(table_id, seat, has_other)

    async def broadcast(self, table_id: str, events: list[dict]) -> None:
        """Send fresh per-seat views to all connections at this table.

        Computes all per-seat views *before* any send (single-threaded
        asyncio guarantees atomicity since :func:`view_for` is sync), then
        sends with awaits.
        """
        try:
            table = tables.get_table(table_id)
        except KeyError:
            return
        # Snapshot of (websocket, payload) tuples to send
        outbox: list[tuple[WebSocket, dict[str, Any]]] = []
        seats_map = self._conns.get(table_id, {})
        for seat, conns in seats_map.items():
            if not conns:
                continue
            view = view_for(table, seat)
            payload = {"type": "state", "state": view, "events": events}
            for ws in list(conns):
                outbox.append((ws, payload))
        for ws, payload in outbox:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                pass


manager = ConnectionManager()
tables.set_broadcaster(manager.broadcast)


# ---------------------------------------------------------------------------
# WS endpoint
# ---------------------------------------------------------------------------


router = APIRouter()


def _allowed_origin(origin: str) -> bool:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    if not raw.strip():
        return True  # no allowlist configured -> allow (dev)
    allowed = {o.strip() for o in raw.split(",") if o.strip()}
    if "*" in allowed:
        return True
    return origin in allowed


@router.websocket("/api/bridge/tables/{table_id}/ws")
async def table_ws(
    ws: WebSocket,
    table_id: str,
    token: str = Query(..., min_length=4, max_length=128),
) -> None:
    origin = ws.headers.get("origin", "")
    if origin and not _allowed_origin(origin):
        await ws.close(code=1008)  # policy violation
        return

    try:
        table = tables.get_table(table_id)
    except KeyError:
        await ws.close(code=1011)  # internal error
        return

    try:
        seat = tables.find_seat_for_token(table, token)
    except PermissionError:
        await ws.close(code=1008)
        return

    await ws.accept()
    await manager.register(table_id, seat, ws)
    try:
        while True:
            msg = await ws.receive_json()
            await _handle_message(table_id, token, seat, msg, ws)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        # malformed payload or transport error -- close politely
        try:
            await ws.close(code=1003)
        except Exception:  # noqa: BLE001
            pass
    finally:
        await manager.unregister(table_id, seat, ws)


async def _handle_message(
    table_id: str,
    token: str,
    seat: Seat,
    msg: dict[str, Any],
    ws: WebSocket,
) -> None:
    if not isinstance(msg, dict):
        await ws.send_json({"type": "error", "message": "invalid message"})
        return
    mtype = msg.get("type")
    if mtype == "ping":
        await ws.send_json({"type": "pong"})
        return
    if mtype == "action":
        try:
            await tables.submit_action(table_id, token, msg.get("action") or {})
        except (ValueError, KeyError, PermissionError) as e:
            await ws.send_json({"type": "error", "message": str(e)})
        return
    if mtype == "next_deal":
        try:
            await tables.start_next_deal(table_id, token)
        except (ValueError, KeyError, PermissionError) as e:
            await ws.send_json({"type": "error", "message": str(e)})
        return
    if mtype == "release_seat":
        await tables.release_seat(table_id, token)
        try:
            await ws.close(code=1000)
        except Exception:  # noqa: BLE001
            pass
        return
    await ws.send_json({"type": "error", "message": f"unknown type {mtype!r}"})
