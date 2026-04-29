"""Per-seat redacted views.

The same Table state is held server-side; this module produces the dict that
gets serialized over the wire to a *specific* seat. Hidden hands stay hidden.

Visibility rules, by phase:
- Auction: each seat sees only their own hand.
- Play (before opening lead is on the table): same as auction.
- Play (after opening lead, dummy revealed): everyone sees dummy's hand;
  declarer additionally sees their own hand (already visible to them).
- Defenders never see declarer's concealed hand.
- After deal complete: optionally we could reveal everything, but we keep the
  concealed-hand rule for now and just include the result.
"""

from __future__ import annotations

from typing import cast

from .auction import calls_to_dicts
from .cards import sort_hand
from .play import Play
from .seats import SEAT_ORDER, Seat, partner
from .state import Deal, Phase, Table


def _hand_payload(cards) -> list[dict]:
    return [c.to_dict() for c in sort_hand(cards)]


def visible_seats(deal: Deal, viewer: Seat) -> set[Seat]:
    """Which seats' hands are visible to the viewer."""
    out: set[Seat] = {viewer}
    if deal.phase in (Phase.PLAY, Phase.COMPLETE):
        play = deal.play
        if play is not None and play.dummy_revealed:
            out.add(play.dummy)
            # Declarer sees both their own hand and dummy (dummy is partner anyway).
    return out


def _seats_payload(table: Table) -> list[dict]:
    """Public seat info: who sits where, what kind, connected, special role."""
    out: list[dict] = []
    for s in SEAT_ORDER:
        owner = table.seat_owners.get(s)
        info: dict = {
            "seat": s.value,
            "kind": table.seat_kind(s),
            "display_name": owner.display_name if owner else None,
            "connected": owner.connected if owner else None,
            "is_declarer": False,
            "is_dummy": False,
        }
        if table.deal is not None and table.deal.play is not None:
            play = table.deal.play
            info["is_declarer"] = (play.contract.declarer == s)
            info["is_dummy"] = (play.dummy_revealed and play.dummy == s)
        out.append(info)
    return out


def view_for(table: Table, viewer: Seat) -> dict:
    deal = table.deal
    payload: dict = {
        "table_id": table.id,
        "viewer": viewer.value,
        "mode": table.mode,
        "can_play": table.can_play(),
        "all_seats_claimed": table.all_seats_claimed(),
        "seats": _seats_payload(table),
        "deal_number": table.deal_number,
        "cumulative_score": dict(table.cumulative_score),
        "history": list(table.history),
    }
    if deal is None:
        payload["phase"] = "no_deal"
        return payload

    payload["phase"] = deal.phase.value
    payload["dealer"] = deal.dealer.value
    payload["auction"] = {
        "calls": calls_to_dicts(deal.auction),
        "to_act": deal.auction.to_act.value if deal.phase == Phase.AUCTION else None,
        "complete": deal.auction.is_complete(),
        "legal_calls": [c.to_dict() for c in deal.auction.legal_calls()] if deal.phase == Phase.AUCTION else [],
    }

    visible = visible_seats(deal, viewer)
    hands_payload: dict[str, dict] = {}
    for s in SEAT_ORDER:
        if s in visible:
            hands_payload[s.value] = {"cards": _hand_payload(deal.hands[s]), "count": len(deal.hands[s])}
        else:
            hands_payload[s.value] = {"cards": None, "count": len(deal.hands[s])}
    payload["hands"] = hands_payload

    if deal.phase in (Phase.PLAY, Phase.COMPLETE) and deal.play is not None:
        play: Play = deal.play
        payload["contract"] = play.contract.to_dict()
        payload["dummy"] = play.dummy.value if play.dummy_revealed else None
        payload["trump"] = play.trump.value if play.trump else None
        payload["tricks"] = {
            "declarer": play.declarer_tricks,
            "defender": play.defender_tricks,
            "needed": play.contract.tricks_required(),
        }
        payload["tricks_played"] = [t.to_dict() for t in play.tricks_played]
        payload["current_trick"] = play.current_trick.to_dict() if play.current_trick else None
        if deal.phase == Phase.PLAY:
            controller = play.acting_controller
            payload["to_act"] = play.to_act.value
            payload["acting_controller"] = controller.value
            # Legal plays only for the seat the viewer controls.
            controlled = {viewer}
            if play.dummy_revealed and viewer == play.contract.declarer:
                controlled.add(play.dummy)
            if play.to_act in controlled and viewer == play.acting_controller:
                payload["legal_plays"] = [c.to_dict() for c in play.legal_plays(play.to_act)]
            else:
                payload["legal_plays"] = []
    else:
        payload["contract"] = None

    if deal.phase == Phase.COMPLETE and deal.result is not None:
        r = deal.result
        payload["result"] = {
            "contract": r.contract.to_dict() if r.contract else None,
            "declarer_tricks": r.declarer_tricks,
            "score": r.score,
        }
        # On a completed deal, optionally reveal all hands so the player can review.
        all_hands_payload: dict[str, dict] = {}
        for s in SEAT_ORDER:
            all_hands_payload[s.value] = {"cards": _hand_payload(deal.hands[s]), "count": len(deal.hands[s])}
        payload["hands_revealed"] = all_hands_payload

    payload["your_turn"] = (
        table.can_play()
        and deal.phase != Phase.COMPLETE
        and deal.acting_controller() == viewer
    )
    return payload
