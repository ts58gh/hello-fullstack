"""Per-seat public view for ongoing :class:`~app.sheng.hand.RunningHand`."""

from __future__ import annotations

from typing import Any

from .cards import PhysCard
from .combos import parse_combo_relaxed

from .friend import FriendCall
from .hand import RunningHand
from .scoring import defenders_threshold
from .tables import ShengRoom
from .trump import TrumpContext


def _friend_call_pub(fc: FriendCall) -> dict[str, Any]:
    return {"nth": fc.nth, "suit": fc.suit.value, "rank": fc.rank}


def _serialize_card(c: PhysCard) -> dict[str, Any]:
    """Include ``suit`` / ``rank`` / ``kind`` for graphical card faces on the client."""

    payload: dict[str, Any] = dict(c.to_dict())
    payload["label"] = c.label()
    return payload


def _legal_option_pub(ctx: TrumpContext, cards: list[PhysCard]) -> dict[str, Any]:
    pb = parse_combo_relaxed(ctx, list(cards))
    return {
        "combo_kind": pb.kind.value,
        "card_ids": [c.cid for c in sorted(cards, key=lambda x: x.cid)],
        "cards": [_serialize_card(c) for c in sorted(cards, key=lambda x: x.cid)],
    }


def _completed_tricks_public(rh: RunningHand) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rh._completed_tricks, start=1):
        out.append(
            {
                "index": i,
                "winner_seat": r.winner_seat,
                "trick_points": r.trick_points,
                "defenders_gained": r.defenders_gained,
                "plays": [
                    {
                        "seat": s,
                        "cards": [_serialize_card(c) for c in bundle],
                    }
                    for s, bundle in r.plays
                ],
            }
        )
    return out


def _defender_trick_points_running(rh: RunningHand) -> int:
    return sum(t.trick_points for t in rh._completed_tricks if t.defenders_gained)


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
        {"seat": s, "cards": [_serialize_card(c) for c in bunch]} for s, bunch in rh.current_trick
    ]

    legal: list[dict[str, Any]] = []
    if rh.phase == "play" and viewer == rh._to_act():
        legal = [_legal_option_pub(rh.trump, cards) for cards in rh.legal_combo_plays(viewer)]

    legal_declare: list[dict[str, Any]] = []
    if rh.phase == "declare":
        legal_declare = rh.legal_declare_options(viewer)

    return {
        "table_id": room.id,
        "game": "sheng",
        "viewer_seat": viewer,
        "phase": rh.phase,
        "num_players": room.num_players,
        "declarer_seat": rh.declarer_seat,
        "bank_declarer_seat": room.bank_declarer_seat,
        "declare_to_act_seat": rh.declare_to_act_seat if rh.phase == "declare" else None,
        "declare_passes_since_change": rh.declare_passes_since_change if rh.phase == "declare" else None,
        "legal_declare": legal_declare,
        "friend_calls": [_friend_call_pub(fc) for fc in room.friend_calls],
        "revealed_friend_seats": list(rh.revealed_friend_seats) if rh.num_players == 6 else [],
        "trump": {
            "level_rank": rh.match_level_rank,
            "trump_suit": rh.trump_suit.value if rh.trump_suit is not None else None,
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
        "completed_tricks": _completed_tricks_public(rh),
        "defender_trick_points_running": _defender_trick_points_running(rh),
        "defenders_threshold": defenders_threshold(room.num_players),
        "trick_index": rh.trick_index,
        "deal_epoch": room.deal_epoch,
    }
