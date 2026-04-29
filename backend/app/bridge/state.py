"""Top-level deal/table state combining auction + play + scoring.

The ``Table`` here holds *all* the multi-player concerns: which seats are
claimed by humans (with a ``client_id`` + ``display_name``), which are
bot-filled, the table's mode (``with_bots`` vs ``humans_only``), running
score, and the current deal. The IO layer (HTTP / WS / lobby) lives one
level up in ``tables.py`` / ``ws.py`` / ``lobby.py``; this module knows
nothing about transports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

from .auction import Auction, Contract, Strain, calls_to_dicts, derive_contract
from .cards import Card, deal_hands
from .play import Play
from .scoring import score_contract
from .seats import SEAT_ORDER, Seat


class Phase(str, Enum):
    AUCTION = "auction"
    PLAY = "play"
    COMPLETE = "complete"


TableMode = Literal["with_bots", "humans_only"]
SeatKind = Literal["human", "bot", "empty"]


@dataclass
class DealResult:
    contract: Contract | None
    declarer_tricks: int
    score: dict  # output of score_contract; or {"passed_out": True, ...}


@dataclass
class Deal:
    """One full bridge deal: auction, then play, then scoring."""

    dealer: Seat
    hands: dict[Seat, list[Card]]
    auction: Auction
    play: Play | None = None
    result: DealResult | None = None
    phase: Phase = Phase.AUCTION

    # ----- factory -------------------------------------------------------

    @classmethod
    def new(cls, dealer: Seat = Seat.NORTH, seed: int | None = None) -> "Deal":
        raw = deal_hands(seed)
        hands = {Seat(k): list(v) for k, v in raw.items()}
        return cls(dealer=dealer, hands=hands, auction=Auction(dealer=dealer))

    # ----- transitions ---------------------------------------------------

    def submit_call(self, kind: str, level: int | None = None, strain: Strain | None = None) -> dict:
        if self.phase != Phase.AUCTION:
            raise ValueError("not in auction phase")
        c = self.auction.call(kind, level=level, strain=strain)
        events: list[dict] = [{"type": "call", "call": c.to_dict()}]
        if self.auction.is_complete():
            contract = derive_contract(self.auction)
            if contract is None:
                self.phase = Phase.COMPLETE
                self.result = DealResult(contract=None, declarer_tricks=0, score={"passed_out": True, "total": 0})
                events.append({"type": "passed_out"})
            else:
                self.phase = Phase.PLAY
                # Hands stay tied to seats; play module mutates them.
                self.play = Play(contract=contract, hands=self.hands)
                events.append({"type": "auction_complete", "contract": contract.to_dict()})
                events.append({"type": "lead", "seat": self.play.current_trick.leader.value})  # type: ignore[union-attr]
        return {"events": events}

    def submit_play(self, seat: Seat, card: Card) -> dict:
        if self.phase != Phase.PLAY:
            raise ValueError("not in play phase")
        assert self.play is not None
        result = self.play.play_card(seat, card)
        events = result["events"]
        if self.play.is_complete():
            self.phase = Phase.COMPLETE
            score = score_contract(self.play.contract, self.play.declarer_tricks)
            self.result = DealResult(
                contract=self.play.contract,
                declarer_tricks=self.play.declarer_tricks,
                score=score,
            )
            events.append({"type": "deal_complete", "result": {
                "contract": self.play.contract.to_dict(),
                "declarer_tricks": self.play.declarer_tricks,
                "score": score,
            }})
        return {"events": events}

    # ----- queries -------------------------------------------------------

    def to_act(self) -> Seat | None:
        if self.phase == Phase.AUCTION:
            return self.auction.to_act
        if self.phase == Phase.PLAY:
            assert self.play is not None
            return self.play.to_act
        return None

    def acting_controller(self) -> Seat | None:
        """The seat that *decides* the next action (declarer plays dummy)."""
        if self.phase == Phase.AUCTION:
            return self.auction.to_act
        if self.phase == Phase.PLAY:
            assert self.play is not None
            return self.play.acting_controller
        return None


@dataclass
class SeatOwner:
    """Identity of a human sitting at a seat."""

    client_id: str
    display_name: str
    last_seen: float = field(default_factory=time.time)
    connected: bool = True

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "display_name": self.display_name,
            "last_seen": self.last_seen,
            "connected": self.connected,
        }


@dataclass
class Table:
    """A persistent bridge table.

    Single deal at a time; deals 1..N in sequence. Score accumulates per side.
    Multi-player concerns live here:

    - ``mode`` controls empty-seat policy (bot-fill vs strict 4 humans).
    - ``seat_owners`` records who (anonymously) claims each seat. ``None``
      means unclaimed, which is bot-controlled in ``with_bots`` and a
      blocker in ``humans_only``.
    - ``seat_tokens`` is the per-seat write capability. Possessing the
      token authorizes actions for that seat over HTTP and WS.
    """

    id: str
    mode: TableMode = "with_bots"
    min_humans: int = 1  # how many human seats must be filled before dealing
    public: bool = True
    host_client_id: str = ""
    created_at: float = field(default_factory=time.time)

    seat_tokens: dict[Seat, Optional[str]] = field(
        default_factory=lambda: {s: None for s in SEAT_ORDER}
    )
    seat_owners: dict[Seat, Optional[SeatOwner]] = field(
        default_factory=lambda: {s: None for s in SEAT_ORDER}
    )

    deal: Deal | None = None
    deal_number: int = 0
    cumulative_score: dict[str, int] = field(default_factory=lambda: {"NS": 0, "EW": 0})
    history: list[dict] = field(default_factory=list)

    # ----- seat-kind derivation ------------------------------------------

    def seat_kind(self, seat: Seat) -> SeatKind:
        if self.seat_owners.get(seat) is not None:
            return "human"
        if self.mode == "with_bots":
            return "bot"
        return "empty"

    def all_seat_kinds(self) -> dict[Seat, SeatKind]:
        return {s: self.seat_kind(s) for s in SEAT_ORDER}

    def humans_count(self) -> int:
        return sum(1 for s in SEAT_ORDER if self.seat_owners.get(s) is not None)

    def all_seats_claimed(self) -> bool:
        return all(self.seat_owners.get(s) is not None for s in SEAT_ORDER)

    def can_play(self) -> bool:
        """Whether the deal can run forward right now.

        Gate is solely ``humans_count() >= min_humans``. ``mode`` only
        controls what happens to seats that nobody owns: in ``with_bots``
        they are bot-controlled; in ``humans_only`` they stay empty
        (which stalls play on that seat until someone claims it).
        """
        if self.deal is None:
            return False
        return self.humans_count() >= self.min_humans

    # ----- deal lifecycle ------------------------------------------------

    def start_new_deal(self, dealer: Seat | None = None, seed: int | None = None) -> Deal:
        # rotate dealer if not specified: dealer rotates clockwise per deal
        if dealer is None:
            if self.deal is None:
                dealer = Seat.NORTH
            else:
                from .seats import next_seat as _ns
                dealer = _ns(self.deal.dealer)
        self.deal = Deal.new(dealer=dealer, seed=seed)
        self.deal_number += 1
        return self.deal

    def commit_deal_to_history(self) -> None:
        if self.deal is None or self.deal.result is None:
            return
        r = self.deal.result
        side = None
        if r.contract is not None:
            from .seats import PARTNERSHIPS
            side = PARTNERSHIPS[r.contract.declarer]
        score_total = r.score.get("total", 0)
        if side and score_total != 0:
            other = "EW" if side == "NS" else "NS"
            if score_total > 0:
                self.cumulative_score[side] += score_total
            else:
                self.cumulative_score[other] += -score_total
        self.history.append({
            "deal_number": self.deal_number,
            "contract": r.contract.to_dict() if r.contract else None,
            "declarer_tricks": r.declarer_tricks,
            "score": r.score,
        })

    # ----- public summary (for lobby listings) ---------------------------

    def lobby_summary(self) -> dict:
        seats: list[dict] = []
        for s in SEAT_ORDER:
            owner = self.seat_owners.get(s)
            seats.append({
                "seat": s.value,
                "kind": self.seat_kind(s),
                "display_name": owner.display_name if owner else None,
                "connected": owner.connected if owner else None,
            })
        deal_phase = self.deal.phase.value if self.deal else "no_deal"
        return {
            "table_id": self.id,
            "mode": self.mode,
            "min_humans": self.min_humans,
            "public": self.public,
            "created_at": self.created_at,
            "deal_phase": deal_phase,
            "deal_number": self.deal_number,
            "humans": self.humans_count(),
            "can_play": self.can_play(),
            "seats": seats,
            "cumulative_score": dict(self.cumulative_score),
        }
