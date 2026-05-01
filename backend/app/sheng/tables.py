"""In-memory ``ShengRoom`` registry + async play entry (WebSocket broadcast)."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .friend import FriendCall
from .hand import RunningHand, declarer_side_seats
from .state import ShengMatch, TeamId


def declarer_team_id(declarer_seat: int, _num_players: int) -> TeamId:
    """Fixed diagonal teams: seats 0,2,(4 …) vs 1,3,(5 …) — declarer parity picks team."""

    return "A" if declarer_seat % 2 == 0 else "B"


def clamp_level(rank: int) -> int:
    return max(2, min(14, rank))


def apply_level_breakdown(sm: ShengMatch, declarer_team: TeamId, lb: dict[str, Any]) -> None:
    opp: TeamId = "B" if declarer_team == "A" else "A"

    dt = clamp_level(sm.teams[declarer_team].level_rank + int(lb.get("dealer_side_delta") or 0))
    dof = clamp_level(sm.teams[opp].level_rank + int(lb.get("defenders_side_delta") or 0))
    sm.teams[declarer_team].level_rank = dt
    sm.teams[opp].level_rank = dof


def validate_friend_calls(num_players: int, fc: tuple[FriendCall, ...]) -> None:
    if num_players == 4 and len(fc) > 0:
        raise ValueError("friend_calls are only supported when num_players == 6")
    if num_players == 6 and fc and len(fc) != 2:
        raise ValueError("six-player mode requires zero or exactly two friend_calls")


def _defender_seat_list(declarer_seat: int, num_players: int) -> list[int]:
    bank_side = declarer_side_seats(declarer_seat, num_players)
    return sorted(s for s in range(num_players) if s not in bank_side)


def next_bank_declarer_seat(declarer_seat: int, num_players: int, lb: dict[str, Any]) -> int:
    """Who opens the next deal as 庄 (trump anchor). MVP: swap to defender team when they take the table."""

    defs = _defender_seat_list(declarer_seat, num_players)
    if lb.get("tie_at_threshold") and lb.get("swap_without_level"):
        return defs[0]
    if int(lb.get("defenders_side_delta") or 0) > 0:
        return defs[0]
    return declarer_seat


@dataclass
class ShengRoom:
    """One table running a :class:`RunningHand`; pair with :class:`ShengMatch` levels.

    ``deal_epoch`` bumps each new deal (for client pacing such as slow-deal animation).
    """

    id: str
    num_players: int
    seat_tokens: dict[int, str]
    match: ShengMatch
    hand: RunningHand
    bank_declarer_seat: int
    friend_calls: tuple[FriendCall, ...] = ()
    deal_epoch: int = 1


_TABLES: dict[str, ShengRoom] = {}
_LOCKS: dict[str, asyncio.Lock] = {}

_MAX_TABLES = 100

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
    except Exception:  # noqa: BLE001
        pass


def _lock_for(table_id: str) -> asyncio.Lock:
    lk = _LOCKS.get(table_id)
    if lk is None:
        lk = asyncio.Lock()
        _LOCKS[table_id] = lk
    return lk


def get_room(table_id: str) -> ShengRoom:
    r = _TABLES.get(table_id)
    if r is None:
        raise KeyError(table_id)
    return r


def find_seat_for_token(room: ShengRoom, token: str) -> int:
    for seat, tok in room.seat_tokens.items():
        if tok == token:
            return seat
    raise PermissionError("bad token")


async def create_room(
    *,
    num_players: int = 4,
    seed: int | None = None,
    declarer_seat: int = 0,
    match_level_rank: int = 2,
    friend_calls: tuple[FriendCall, ...] = (),
) -> tuple[ShengRoom, dict[int, str]]:
    if len(_TABLES) >= _MAX_TABLES:
        _TABLES.clear()  # naive reset
    if num_players not in (4, 6):
        raise ValueError("num_players must be 4 or 6")
    validate_friend_calls(num_players, friend_calls)
    tid = secrets.token_urlsafe(8)
    toks = {i: secrets.token_urlsafe(14) for i in range(num_players)}
    bd = declarer_seat % num_players
    match = ShengMatch()
    match.teams[declarer_team_id(bd, num_players)].level_rank = match_level_rank
    hand = RunningHand.deal_new(
        num_players=num_players,
        seed=seed,
        declarer_seat=bd,
        match_level_rank=match_level_rank,
        friend_calls=friend_calls,
    )
    room = ShengRoom(
        id=tid,
        num_players=num_players,
        seat_tokens=dict(toks),
        match=match,
        hand=hand,
        bank_declarer_seat=bd,
        friend_calls=tuple(friend_calls),
    )
    _TABLES[tid] = room
    return room, toks


async def submit_declare(table_id: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with _lock_for(table_id):
        room = get_room(table_id)
        seat = find_seat_for_token(room, token)
        out = room.hand.declare_submit(seat, payload)
    await _broadcast(table_id, out.get("events") or [])
    return out


async def submit_play(table_id: str, token: str, card_ids: list[int]) -> dict[str, Any]:
    async with _lock_for(table_id):
        room = get_room(table_id)
        seat = find_seat_for_token(room, token)
        out = room.hand.play_cards(seat, list(card_ids))
        if room.hand.phase == "scored" and room.hand.result is not None:
            lb = room.hand.result.level_breakdown
            scorer_declarer = room.hand.declarer_seat
            apply_level_breakdown(
                room.match,
                declarer_team_id(scorer_declarer, room.num_players),
                lb,
            )
            room.bank_declarer_seat = next_bank_declarer_seat(scorer_declarer, room.num_players, lb)
    await _broadcast(table_id, out.get("events") or [])
    return out


async def start_next_hand(
    table_id: str,
    *,
    seed: int | None = None,
    friend_calls: tuple[FriendCall, ...] | None = None,
) -> dict[str, Any]:
    async with _lock_for(table_id):
        room = get_room(table_id)
        if room.hand.phase != "scored":
            raise ValueError("hand still in progress")
        bank = room.bank_declarer_seat % room.num_players
        team = declarer_team_id(bank, room.num_players)
        match_rank = room.match.teams[team].level_rank
        fc_eff = room.friend_calls if friend_calls is None else tuple(friend_calls)
        validate_friend_calls(room.num_players, fc_eff)
        if friend_calls is not None:
            room.friend_calls = fc_eff
        room.hand = RunningHand.deal_new(
            num_players=room.num_players,
            seed=seed,
            declarer_seat=bank,
            match_level_rank=match_rank,
            friend_calls=fc_eff,
        )
        room.bank_declarer_seat = bank
        room.deal_epoch += 1
    events = [{"type": "next_hand"}]
    await _broadcast(table_id, events)
    return {"events": events}
