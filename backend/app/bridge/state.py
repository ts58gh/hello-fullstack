"""Top-level deal/table state combining auction + play + scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .auction import Auction, Contract, Strain, calls_to_dicts, derive_contract
from .cards import Card, deal_hands
from .play import Play
from .scoring import score_contract
from .seats import SEAT_ORDER, Seat


class Phase(str, Enum):
    AUCTION = "auction"
    PLAY = "play"
    COMPLETE = "complete"


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
class Table:
    """A persistent table that runs deals one after another.

    Single deal at a time; deals 1..N in sequence. Score accumulates per side.
    """

    id: str
    seat_tokens: dict[Seat, str | None] = field(default_factory=lambda: {s: None for s in SEAT_ORDER})
    seat_kinds: dict[Seat, Literal["human", "bot"]] = field(default_factory=dict)
    deal: Deal | None = None
    deal_number: int = 0
    cumulative_score: dict[str, int] = field(default_factory=lambda: {"NS": 0, "EW": 0})
    history: list[dict] = field(default_factory=list)

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
