"""Per-seat public view for ongoing :class:`~app.sheng.hand.RunningHand`."""

from __future__ import annotations

from typing import Any

from .cards import PhysCard
from .friend import FriendCall
from .tables import ShengRoom


def _friend_call_pub(fc: FriendCall) -> dict[str, Any]:
    return {"nth": fc.nth, "suit": fc.suit.value, "rank": fc.rank}


def _serialize_card(c: PhysCard) -> dict[str, Any]:
    return {"cid": c.cid, "label": c.label()}


def serial_hands(room: ShengRoom, viewer: int) -> list[Any]:
    """Own hand exposes full cards; opponents only expose counts."""

    out: list[Any] = []
    for seat, hz in enumerate(room.hand.hands):
        if seat == viewer:
            out.append([_serialize_card(x) for x in hz])
        else:
            out.append({"count": len(hz)})
    return out


def view_for(room: ShengRoom, viewer: int) -> dict[str, Any]:
    rh = room.hand

    kitty_public: dict[str, Any] = {"count": len(rh.kitty)}

    summary = None
    if rh.phase == "scored" and rh.result is not None:
        summary = {
            "defender_points_final": rh.result.defender_points_final,
            "defender_points_tricks_only": rh.result.defender_points_tricks_only,
            "kitty_bonus_to_defenders": rh.result.kitty_bonus_to_defenders,
            "level_change": rh.result.level_breakdown,
            "declarer_seat": rh.result.declarer_seat,
            "last_trick_winner": rh.result.last_trick_winner,
        }

    # Cards played to the current trick are public to all watchers.
    current_trick = [
        {"seat": s, "card": _serialize_card(c)}
        for s, c in rh.current_trick
    ]

    legal: list[dict[str, Any]] = []
    if rh.phase == "play" and viewer == rh._to_act():
        legal = [{"cid": c.cid, "label": c.label()} for c in rh.legal_single_plays(viewer)]

    return {
        "table_id": room.id,
        "game": "sheng",
        "viewer_seat": viewer,
        "phase": rh.phase,
        "num_players": room.num_players,
        "declarer_seat": rh.declarer_seat,
        "bank_declarer_seat": room.bank_declarer_seat,
        "friend_calls": [_friend_call_pub(fc) for fc in room.friend_calls],
        "revealed_friend_seats": list(rh.revealed_friend_seats) if rh.num_players == 6 else [],
        "trump": {
            "level_rank": rh.match_level_rank,
            "trump_suit": rh.trump_suit.value if rh.trump_suit else None,
        },
        "leader": rh.leader,
        "current_trick": current_trick,
        "hands": serial_hands(room, viewer),
        "kitty": kitty_public,
        "teams": {
            "A": room.match.teams["A"].level_rank,
            "B": room.match.teams["B"].level_rank,
        },
        "hand_summary": summary,
        "legal_plays": legal,
        "to_act_seat": rh._to_act() if rh.phase == "play" else None,
    }
