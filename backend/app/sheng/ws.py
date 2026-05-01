"""WebSocket fan-out for ``ShengRoom`` tables (separate broadcaster from bridge)."""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from . import tables as sheng_tables
from .friend import parse_friend_calls
from .views import view_for


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[str, dict[int, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self._lock = asyncio.Lock()

    async def register(self, table_id: str, seat: int, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[table_id][seat].add(ws)
        try:
            room = sheng_tables.get_room(table_id)
        except KeyError:
            return
        view = view_for(room, seat)
        try:
            await ws.send_json({"type": "state", "state": view, "events": []})
        except Exception:  # noqa: BLE001
            pass

    async def unregister(self, table_id: str, seat: int, ws: WebSocket) -> None:
        async with self._lock:
            seat_conns = self._conns.get(table_id, {}).get(seat)
            if seat_conns is not None:
                seat_conns.discard(ws)

    async def broadcast(self, table_id: str, events: list[dict]) -> None:
        try:
            room = sheng_tables.get_room(table_id)
        except KeyError:
            return
        outbox: list[tuple[WebSocket, dict[str, Any]]] = []
        seats_map = self._conns.get(table_id, {})
        for seat, conns in seats_map.items():
            if not conns:
                continue
            payload = {"type": "state", "state": view_for(room, seat), "events": events}
            for ws in list(conns):
                outbox.append((ws, payload))
        for ws, payload in outbox:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                pass


manager = ConnectionManager()
sheng_tables.set_broadcaster(manager.broadcast)

router = APIRouter()


def _allowed_origin(origin: str) -> bool:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    if not raw.strip():
        return True
    allowed = {o.strip() for o in raw.split(",") if o.strip()}
    if "*" in allowed:
        return True
    return origin in allowed


@router.websocket("/api/sheng/tables/{table_id}/ws")
async def sheng_table_ws(
    ws: WebSocket,
    table_id: str,
    token: str = Query(..., min_length=4, max_length=256),
) -> None:
    origin = ws.headers.get("origin", "")
    if origin and not _allowed_origin(origin):
        await ws.close(code=1008)
        return

    try:
        room = sheng_tables.get_room(table_id)
    except KeyError:
        await ws.close(code=1011)
        return

    try:
        seat = sheng_tables.find_seat_for_token(room, token)
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
        try:
            await ws.close(code=1003)
        except Exception:  # noqa: BLE001
            pass
    finally:
        await manager.unregister(table_id, seat, ws)


async def _handle_message(
    table_id: str,
    token: str,
    _seat: int,
    msg: Any,
    ws: WebSocket,
) -> None:
    if not isinstance(msg, dict):
        await ws.send_json({"type": "error", "message": "invalid message"})
        return
    mtype = msg.get("type")
    if mtype == "ping":
        await ws.send_json({"type": "pong"})
        return
    if mtype == "declare":
        try:
            act = msg.get("action")
            if not isinstance(act, str):
                raise ValueError("declare.action required")
            payload: dict[str, Any] = {"action": act}
            if msg.get("suit") is not None:
                payload["suit"] = str(msg["suit"])
            await sheng_tables.submit_declare(table_id, token, payload)
        except (ValueError, KeyError, PermissionError, TypeError) as e:
            await ws.send_json({"type": "error", "message": str(e)})
        return
    if mtype == "action":
        try:
            raw_ids = msg.get("card_ids")
            if isinstance(raw_ids, list) and raw_ids:
                cids = [int(x) for x in raw_ids]
            elif msg.get("card_id") is not None:
                cids = [int(msg["card_id"])]
            else:
                raise ValueError("card_ids (non-empty) or card_id required")
            await sheng_tables.submit_play(table_id, token, cids)
        except (ValueError, KeyError, PermissionError, TypeError) as e:
            await ws.send_json({"type": "error", "message": str(e)})
        return
    if mtype == "next_hand":
        try:
            seed = msg.get("seed")
            if "friend_calls" not in msg or msg["friend_calls"] is None:
                fc_override = None
            else:
                raw = msg["friend_calls"]
                if not isinstance(raw, list):
                    raise ValueError("friend_calls must be a list or null")
                fc_override = parse_friend_calls(raw)
            await sheng_tables.start_next_hand(
                table_id,
                seed=int(seed) if seed is not None else None,
                friend_calls=fc_override,
            )
        except (ValueError, KeyError) as e:
            await ws.send_json({"type": "error", "message": str(e)})
        return
    await ws.send_json({"type": "error", "message": f"unknown type {mtype!r}"})
