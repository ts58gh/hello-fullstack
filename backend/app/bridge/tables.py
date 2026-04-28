"""In-memory tables store + bot orchestration loop.

This is the *only* layer above `state` that knows about identity (tokens) and
about which seats are bot-controlled. The HTTP / WS layer goes here.

For multi-player later, swap `seat_kinds` so all 4 are "human" and skip the
bot loop -- everything else (rules, views, scoring) is unchanged.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Literal

from .auction import Strain
from .bots import choose_call, choose_play
from .cards import Card, Suit
from .seats import SEAT_ORDER, Seat
from .state import Deal, Phase, Table


_TABLES: dict[str, Table] = {}
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()
_MAX_TABLES = 200


def _lock_for(table_id: str) -> threading.Lock:
    with _GLOBAL_LOCK:
        lk = _LOCKS.get(table_id)
        if lk is None:
            lk = threading.Lock()
            _LOCKS[table_id] = lk
        return lk


def create_solo_table(human_seat: Seat = Seat.SOUTH, seed: int | None = None) -> tuple[Table, str]:
    """Create a new table with one human seat (default South) and 3 bots.

    Returns (table, human_token). The human_token must be presented for any
    write actions and to scope the per-seat view.
    """
    with _GLOBAL_LOCK:
        if len(_TABLES) >= _MAX_TABLES:
            # Rough garbage collection: drop the oldest finished tables.
            for tid in list(_TABLES):
                t = _TABLES[tid]
                if t.deal is None or t.deal.phase == Phase.COMPLETE:
                    _TABLES.pop(tid, None)
                    _LOCKS.pop(tid, None)
                    if len(_TABLES) < _MAX_TABLES:
                        break

        table_id = secrets.token_urlsafe(8)
        token = secrets.token_urlsafe(16)
        table = Table(id=table_id)
        for s in SEAT_ORDER:
            if s == human_seat:
                table.seat_kinds[s] = "human"
                table.seat_tokens[s] = token
            else:
                table.seat_kinds[s] = "bot"
                table.seat_tokens[s] = None
        _TABLES[table_id] = table

    table.start_new_deal(dealer=Seat.NORTH, seed=seed)
    return table, token


def get_table(table_id: str) -> Table:
    t = _TABLES.get(table_id)
    if t is None:
        raise KeyError(table_id)
    return t


def find_seat_for_token(table: Table, token: str) -> Seat:
    for s in SEAT_ORDER:
        if table.seat_tokens.get(s) == token:
            return s
    raise PermissionError("invalid token for table")


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------


def submit_action(table_id: str, token: str, action: dict) -> dict:
    """Execute a human action and run the bot loop until human's turn or done.

    `action` schema:
    - {"kind": "pass" | "double" | "redouble"}
    - {"kind": "bid", "level": int, "strain": "C|D|H|S|NT"}
    - {"kind": "play", "card": {"suit": "C|D|H|S", "rank": int}}
    """
    lock = _lock_for(table_id)
    with lock:
        table = get_table(table_id)
        seat = find_seat_for_token(table, token)
        deal = table.deal
        if deal is None:
            raise ValueError("no active deal")

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

        events.extend(_advance_bots(table))

        if deal.phase == Phase.COMPLETE:
            table.commit_deal_to_history()

        return {"events": events}


def start_next_deal(table_id: str, token: str, seed: int | None = None) -> dict:
    lock = _lock_for(table_id)
    with lock:
        table = get_table(table_id)
        find_seat_for_token(table, token)  # validate token; raises if bad
        if table.deal is not None and table.deal.phase != Phase.COMPLETE:
            raise ValueError("current deal not finished")
        table.start_new_deal(seed=seed)
        events: list[dict] = [{"type": "new_deal", "deal_number": table.deal_number}]
        events.extend(_advance_bots(table))
        return {"events": events}


# ---------------------------------------------------------------------------
# Bot loop
# ---------------------------------------------------------------------------


def _advance_bots(table: Table) -> list[dict]:
    """Run bots until either the controller is a human or the deal completes.

    Caller must hold the per-table lock. Returns events generated.
    """
    events: list[dict] = []
    deal = table.deal
    if deal is None:
        return events

    safety = 0
    while deal.phase != Phase.COMPLETE:
        controller = deal.acting_controller()
        if controller is None:
            break
        if table.seat_kinds.get(controller) != "bot":
            break
        safety += 1
        if safety > 200:
            raise RuntimeError("bot loop runaway")

        if deal.phase == Phase.AUCTION:
            call = choose_call(deal, controller)
            res = deal.submit_call(
                call.kind,
                level=call.level,
                strain=call.strain,
            )
            events.extend(res["events"])
        elif deal.phase == Phase.PLAY:
            assert deal.play is not None
            playing_seat = deal.play.to_act
            card = choose_play(deal, playing_seat, controller)
            res = deal.submit_play(playing_seat, card)
            events.extend(res["events"])
        else:
            break

    return events
