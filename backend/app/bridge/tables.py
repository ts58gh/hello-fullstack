"""Async in-memory tables store + bot ticker + grace-timer registry.

This module is the only layer above the pure engine that knows about
identity (per-seat tokens) and bot orchestration. The HTTP and WebSocket
layers (`api.py`, `ws.py`) live above it and call into the async
operations defined here.

Concurrency model
-----------------
- One ``asyncio.Lock`` per table id; all mutating operations acquire it.
- One ``asyncio.Task`` per table id for the bot ticker (``_bot_ticker``),
  which advances bot moves with human-friendly pacing and self-exits the
  moment a human's turn arrives or the deal completes.
- One ``asyncio.Task`` per ``(table_id, seat)`` for the disconnect grace
  timer; cancelled on reconnect.

Broadcasting
------------
``ws.py`` registers a ``broadcaster`` here via ``set_broadcaster(...)`` so
that every state mutation can fan out to connected WebSockets without a
hard import cycle. If no broadcaster is registered (e.g. in unit tests
without WS), ``_broadcast`` is a silent no-op.
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from .auction import Strain
from .bots import choose_call, choose_play
from .cards import Card, Suit
from .seats import SEAT_ORDER, Seat
from .state import Deal, Phase, SeatOwner, Table, TableMode


# ---------------------------------------------------------------------------
# Registry + locks + tasks
# ---------------------------------------------------------------------------


_TABLES: dict[str, Table] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_TICKER_TASKS: dict[str, asyncio.Task] = {}
_GRACE_TASKS: dict[tuple[str, Seat], asyncio.Task] = {}

_MAX_TABLES = 200
_BOT_PACE_SEC = 0.9
_GRACE_SEC = 30.0


# ---------------------------------------------------------------------------
# Broadcaster registration (set by ws.py at import time)
# ---------------------------------------------------------------------------


BroadcastFn = Callable[[str, list[dict]], Awaitable[None]]
_broadcaster: Optional[BroadcastFn] = None


def set_broadcaster(fn: Optional[BroadcastFn]) -> None:
    global _broadcaster
    _broadcaster = fn


async def _broadcast(table_id: str, events: list[dict]) -> None:
    if _broadcaster is None:
        return
    try:
        await _broadcaster(table_id, events)
    except Exception:  # noqa: BLE001 -- broadcasting must not raise into callers
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lock_for(table_id: str) -> asyncio.Lock:
    lk = _LOCKS.get(table_id)
    if lk is None:
        lk = asyncio.Lock()
        _LOCKS[table_id] = lk
    return lk


def _gc_finished_tables() -> None:
    if len(_TABLES) < _MAX_TABLES:
        return
    for tid in list(_TABLES):
        t = _TABLES[tid]
        if t.deal is None or t.deal.phase == Phase.COMPLETE:
            _TABLES.pop(tid, None)
            _LOCKS.pop(tid, None)
            task = _TICKER_TASKS.pop(tid, None)
            if task is not None and not task.done():
                task.cancel()
            if len(_TABLES) < _MAX_TABLES:
                break


def get_table(table_id: str) -> Table:
    t = _TABLES.get(table_id)
    if t is None:
        raise KeyError(table_id)
    return t


def list_public_tables() -> list[dict]:
    return [t.lobby_summary() for t in _TABLES.values() if t.public]


def find_seat_for_token(table: Table, token: str) -> Seat:
    for s in SEAT_ORDER:
        if table.seat_tokens.get(s) == token:
            return s
    raise PermissionError("invalid token for table")


def find_seat_for_client(table: Table, client_id: str) -> Optional[Seat]:
    for s in SEAT_ORDER:
        owner = table.seat_owners.get(s)
        if owner is not None and owner.client_id == client_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


async def create_table_full(
    mode: TableMode,
    host_client_id: str,
    host_display_name: str,
    host_seat: Optional[Seat] = None,
    public: bool = True,
    seed: Optional[int] = None,
) -> tuple[Table, Optional[str]]:
    """Create a new table.

    If ``host_seat`` is given, the host is auto-seated and the returned token
    is theirs. If not, the table is created with no humans yet (only useful
    for ``with_bots`` tables, which start playing immediately).

    For ``with_bots`` tables the first deal is started right away. For
    ``humans_only`` tables the first deal starts only when all 4 seats are
    claimed (which is enforced inside :func:`claim_seat`).
    """
    _gc_finished_tables()
    if not host_client_id:
        host_client_id = str(uuid.uuid4())

    table_id = secrets.token_urlsafe(8)
    table = Table(
        id=table_id,
        mode=mode,
        public=public,
        host_client_id=host_client_id,
    )
    _TABLES[table_id] = table

    host_token: Optional[str] = None
    async with _lock_for(table_id):
        if host_seat is not None:
            host_token = _claim_seat_unlocked(
                table, host_seat, host_client_id, host_display_name
            )
        # Start the first deal if appropriate
        if table.deal is None and (
            mode == "with_bots" or table.all_seats_claimed()
        ):
            table.start_new_deal(dealer=Seat.NORTH, seed=seed)

    _kick_bot_ticker(table_id)
    return table, host_token


async def create_solo_table(
    human_seat: Seat = Seat.SOUTH,
    seed: int | None = None,
    display_name: str = "You",
    client_id: Optional[str] = None,
) -> tuple[Table, str]:
    """Backwards-compatible solo shortcut: ``with_bots`` table, host at South."""
    table, token = await create_table_full(
        mode="with_bots",
        host_client_id=client_id or str(uuid.uuid4()),
        host_display_name=display_name,
        host_seat=human_seat,
        public=True,
        seed=seed,
    )
    assert token is not None  # we passed host_seat
    return table, token


# ---------------------------------------------------------------------------
# Seat claiming / releasing (also used for reconnect)
# ---------------------------------------------------------------------------


def _claim_seat_unlocked(
    table: Table,
    seat: Seat,
    client_id: str,
    display_name: str,
) -> str:
    """Mutate the table to register `seat` as belonging to `client_id`.

    Reclaim-by-same-client is allowed (useful for refreshing a tab). The
    seat token is preserved when it already exists.
    """
    if not client_id:
        raise ValueError("client_id required")
    existing = table.seat_owners.get(seat)
    if existing is not None and existing.client_id != client_id:
        raise PermissionError(f"seat {seat.value} is already taken")

    if existing is not None:
        existing.connected = True
        existing.last_seen = time.time()
        if display_name:
            existing.display_name = display_name
        token = table.seat_tokens.get(seat)
        if not token:
            token = secrets.token_urlsafe(16)
            table.seat_tokens[seat] = token
        return token

    # Fresh claim. If a human had previously sat here under a different
    # identity in humans_only mode, the prior state was already vacated by
    # the grace timer; the deal's hand is preserved on the seat.
    token = secrets.token_urlsafe(16)
    table.seat_owners[seat] = SeatOwner(
        client_id=client_id, display_name=(display_name or "Guest")
    )
    table.seat_tokens[seat] = token
    return token


async def claim_seat(
    table_id: str,
    seat: Seat,
    client_id: str,
    display_name: str,
) -> str:
    """Claim ``seat`` at ``table_id`` for ``client_id``. Returns the seat token.

    Idempotent for the same ``client_id`` (reclaim resets the connection
    flag and may rotate the display name). If a different client already
    holds the seat, ``PermissionError`` is raised.
    """
    async with _lock_for(table_id):
        table = get_table(table_id)
        token = _claim_seat_unlocked(table, seat, client_id, display_name)
        # Cancel any pending grace timer for this seat now that someone holds it.
        _cancel_grace(table_id, seat)
        events = [
            {
                "type": "seat_claimed",
                "seat": seat.value,
                "display_name": table.seat_owners[seat].display_name,  # type: ignore[union-attr]
            }
        ]
        # Possibly start the first deal now that the table can play
        if table.deal is None and (
            table.mode == "with_bots" or table.all_seats_claimed()
        ):
            table.start_new_deal(dealer=Seat.NORTH)
            events.append({"type": "new_deal", "deal_number": table.deal_number})

    await _broadcast(table_id, events)
    _kick_bot_ticker(table_id)
    return token


async def release_seat(table_id: str, token: str) -> Seat | None:
    """Voluntary leave; returns the seat that was released (or None)."""
    async with _lock_for(table_id):
        table = _TABLES.get(table_id)
        if table is None:
            return None
        try:
            seat = find_seat_for_token(table, token)
        except PermissionError:
            return None
        table.seat_owners[seat] = None
        table.seat_tokens[seat] = None
        events = [{"type": "seat_released", "seat": seat.value}]
    await _broadcast(table_id, events)
    _kick_bot_ticker(table_id)
    return seat


# ---------------------------------------------------------------------------
# Connect / disconnect signals (called by ws.py)
# ---------------------------------------------------------------------------


async def on_seat_connect(table_id: str, seat: Seat) -> None:
    """A websocket has just opened for this seat."""
    _cancel_grace(table_id, seat)
    async with _lock_for(table_id):
        table = _TABLES.get(table_id)
        if table is None:
            return
        owner = table.seat_owners.get(seat)
        if owner is None:
            return
        owner.connected = True
        owner.last_seen = time.time()
        events = [{"type": "seat_connected", "seat": seat.value}]
    await _broadcast(table_id, events)


async def on_seat_disconnect(table_id: str, seat: Seat, has_other_conns: bool) -> None:
    """A websocket has closed for this seat.

    If the same human still has another connection (e.g. another browser
    tab) we leave them marked connected. Otherwise mark them disconnected
    and start the grace timer.
    """
    if has_other_conns:
        return
    async with _lock_for(table_id):
        table = _TABLES.get(table_id)
        if table is None:
            return
        owner = table.seat_owners.get(seat)
        if owner is None:
            return
        owner.connected = False
        owner.last_seen = time.time()
        events = [{"type": "seat_disconnected", "seat": seat.value}]
    await _broadcast(table_id, events)
    _start_grace(table_id, seat)


def _start_grace(table_id: str, seat: Seat) -> None:
    key = (table_id, seat)
    existing = _GRACE_TASKS.pop(key, None)
    if existing is not None and not existing.done():
        existing.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _GRACE_TASKS[key] = loop.create_task(_grace_expire(table_id, seat))


def _cancel_grace(table_id: str, seat: Seat) -> None:
    task = _GRACE_TASKS.pop((table_id, seat), None)
    if task is not None and not task.done():
        task.cancel()


async def _grace_expire(table_id: str, seat: Seat) -> None:
    try:
        await asyncio.sleep(_GRACE_SEC)
    except asyncio.CancelledError:
        return
    async with _lock_for(table_id):
        table = _TABLES.get(table_id)
        if table is None:
            return
        owner = table.seat_owners.get(seat)
        if owner is None or owner.connected:
            return
        # Vacate the seat. The deal's hand for this seat is preserved
        # so a future claimer can take over mid-deal in humans_only.
        table.seat_owners[seat] = None
        table.seat_tokens[seat] = None
        events = [
            {"type": "seat_vacated", "seat": seat.value, "reason": "grace_expired"}
        ]
    await _broadcast(table_id, events)
    _kick_bot_ticker(table_id)


# ---------------------------------------------------------------------------
# Action submission
# ---------------------------------------------------------------------------


async def submit_action(table_id: str, token: str, action: dict[str, Any]) -> dict:
    """Execute a human action. Returns events that resulted from this call.

    Bot follow-ups happen asynchronously inside the bot ticker and are
    broadcast separately over WS.
    """
    async with _lock_for(table_id):
        table = get_table(table_id)
        seat = find_seat_for_token(table, token)
        deal = table.deal
        if deal is None:
            raise ValueError("no active deal")
        if not table.can_play():
            raise ValueError("waiting for all seats to be claimed")

        events: list[dict] = []
        kind = action.get("kind")

        if deal.phase == Phase.AUCTION:
            if seat != deal.auction.to_act:
                raise ValueError("not your turn to bid")
            if kind in ("pass", "double", "redouble"):
                result = deal.submit_call(kind)
            elif kind == "bid":
                level = action.get("level")
                strain_raw = action.get("strain")
                if not isinstance(level, int) or strain_raw not in {s.value for s in Strain}:
                    raise ValueError("bid requires integer level and valid strain")
                result = deal.submit_call("bid", level=level, strain=Strain(strain_raw))
            else:
                raise ValueError(f"unsupported action in auction: {kind!r}")
            events.extend(result["events"])

        elif deal.phase == Phase.PLAY:
            assert deal.play is not None
            controller = deal.play.acting_controller
            if controller != seat:
                raise ValueError("not your turn to play")
            if kind != "play":
                raise ValueError("expected a play action")
            card_raw = action.get("card") or {}
            try:
                suit = Suit(card_raw.get("suit"))
                rank = int(card_raw.get("rank"))
            except Exception as e:
                raise ValueError(f"invalid card payload: {e}") from e
            card = Card(suit=suit, rank=rank)
            playing_seat = deal.play.to_act
            result = deal.submit_play(playing_seat, card)
            events.extend(result["events"])

        else:
            raise ValueError("deal already complete")

        if deal.phase == Phase.COMPLETE:
            table.commit_deal_to_history()

    await _broadcast(table_id, events)
    _kick_bot_ticker(table_id)
    return {"events": events}


async def start_next_deal(table_id: str, token: str, seed: int | None = None) -> dict:
    async with _lock_for(table_id):
        table = get_table(table_id)
        find_seat_for_token(table, token)
        if table.deal is not None and table.deal.phase != Phase.COMPLETE:
            raise ValueError("current deal not finished")
        if table.mode == "humans_only" and not table.all_seats_claimed():
            raise ValueError("waiting for all seats to be claimed")
        table.start_new_deal(seed=seed)
        events = [{"type": "new_deal", "deal_number": table.deal_number}]
    await _broadcast(table_id, events)
    _kick_bot_ticker(table_id)
    return {"events": events}


# ---------------------------------------------------------------------------
# Bot ticker
# ---------------------------------------------------------------------------


def _kick_bot_ticker(table_id: str) -> None:
    """Ensure a bot ticker is running. No-op if one is already in flight."""
    existing = _TICKER_TASKS.get(table_id)
    if existing is not None and not existing.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # tests without an event loop
    _TICKER_TASKS[table_id] = loop.create_task(_bot_ticker(table_id))


async def _bot_ticker(table_id: str) -> None:
    """Advance bot moves one at a time with pacing.

    Acquires the per-table lock for each step. Self-exits when the
    controller is human, the table cannot play (humans_only with empty
    seats), or the deal completes.
    """
    try:
        while True:
            events: list[dict] = []
            async with _lock_for(table_id):
                table = _TABLES.get(table_id)
                if table is None:
                    return
                deal = table.deal
                if deal is None or deal.phase == Phase.COMPLETE:
                    return
                if not table.can_play():
                    return
                controller = deal.acting_controller()
                if controller is None:
                    return
                if table.seat_kind(controller) != "bot":
                    return

                if deal.phase == Phase.AUCTION:
                    call = choose_call(deal, controller)
                    res = deal.submit_call(call.kind, level=call.level, strain=call.strain)
                else:
                    assert deal.play is not None
                    playing_seat = deal.play.to_act
                    card = choose_play(deal, playing_seat, controller)
                    res = deal.submit_play(playing_seat, card)
                events = res["events"]
                if deal.phase == Phase.COMPLETE:
                    table.commit_deal_to_history()

            await _broadcast(table_id, events)
            await asyncio.sleep(_BOT_PACE_SEC)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        return
