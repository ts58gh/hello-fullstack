"""Run one finished 升级 hand (multi-card combos: single / pair / triple / plain tractor).

First trick opens **left of declarer / 庄家右手** — ``leader=(declarer+1)%n``;
within the hand subsequent tricks open with the trick winner.

Six-player **找朋友**：可声明两张朋友牌（揭牌由 :mod:`friend` 跟踪）。
若本副 **两张朋友牌均已揭牌** 且与庄家共 **三** 个不同座位，则 **捡分 / 底牌奖** 按 **3v3**（庄方 vs 三门）计算；否则 **回退为对角两队**。

Kitty stays aside until scoring: defenders add ``kitty_multiplier × kitty_points``
to their tally **only when a defender-seat player wins the last trick**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .cards import PhysCard, Suit, build_shoe, deal, shoe_size_for_players
from .combo_legal import combo_trick_winner_seat, legal_plays_for_turn
from .friend import FriendCall, FriendPlayTracker
from .scoring import (
    defenders_threshold,
    kitty_multiplier_for_last_trick,
    level_change_after_deal,
    point_value,
    points_in_cards,
)
from .trump import TrumpContext


def teammate_seat(declarer_seat: int, num_players: int) -> int:
    assert num_players in (4, 6)
    return (declarer_seat + num_players // 2) % num_players


def declarer_side_seats(declarer_seat: int, num_players: int) -> set[int]:
    return {declarer_seat, teammate_seat(declarer_seat, num_players)}


TeamTag = Literal["declarer_side", "defender_side"]


def seat_side(declarer_seat: int, num_players: int, seat: int) -> TeamTag:
    return "declarer_side" if seat in declarer_side_seats(declarer_seat, num_players) else "defender_side"


@dataclass
class HandResult:
    defender_points_final: int
    defender_points_tricks_only: int
    kitty_bonus_to_defenders: int
    last_trick_winner: int
    level_breakdown: dict
    declarer_seat: int


@dataclass(frozen=True)
class CompletedTrickRecord:
    """Finished trick — each seat contributes a bundle of PhysCards."""

    winner_seat: int
    trick_points: int
    defenders_gained: bool
    plays: tuple[tuple[int, tuple[PhysCard, ...]], ...]


@dataclass
class RunningHand:
    num_players: int
    seed: int | None
    declarer_seat: int
    match_level_rank: int
    trump_suit: Suit
    hands: list[list[PhysCard]]
    kitty: list[PhysCard]
    trump: TrumpContext
    leader: int
    current_trick: list[tuple[int, tuple[PhysCard, ...]]] = field(default_factory=list)
    trick_index: int = 0
    friend_tracker: FriendPlayTracker | None = None
    friend_calls: tuple[FriendCall, ...] = ()
    _completed_tricks: list[CompletedTrickRecord] = field(default_factory=list, repr=False)
    _revealed_friend_seats: set[int] = field(default_factory=set, repr=False)
    phase: Literal["play", "scored"] = "play"
    result: HandResult | None = None

    @property
    def revealed_friend_seats(self) -> tuple[int, ...]:
        """Seats that have been revealed as 朋友 (6 人找朋友)."""

        return tuple(sorted(self._revealed_friend_seats))

    @classmethod
    def deal_new(
        cls,
        *,
        num_players: int = 4,
        seed: int | None = None,
        declarer_seat: int = 0,
        match_level_rank: int = 5,
        trump_suit: Suit = Suit.HEARTS,
        friend_calls: tuple[FriendCall, ...] = (),
    ) -> "RunningHand":
        if num_players not in (4, 6):
            raise ValueError("num_players must be 4 or 6")
        nd = shoe_size_for_players(num_players)
        shoe = build_shoe(nd)
        hands_t, kitty = deal(shoe, num_players, seed=seed)
        trump = TrumpContext(level_rank=match_level_rank, trump_suit=trump_suit)
        fc_tuple = tuple(friend_calls)
        tracker = FriendPlayTracker(fc_tuple) if fc_tuple else None
        base = declarer_seat % num_players
        leader = (base + 1) % num_players
        return cls(
            num_players=num_players,
            seed=seed,
            declarer_seat=base,
            match_level_rank=match_level_rank,
            trump_suit=trump_suit,
            hands=list(map(list, hands_t)),
            kitty=list(kitty),
            trump=trump,
            leader=leader,
            friend_tracker=tracker,
            friend_calls=fc_tuple,
        )

    def _take_cards_ordered(self, seat: int, cid_order: list[int]) -> tuple[PhysCard, ...]:
        if len(set(cid_order)) != len(cid_order):
            raise ValueError("duplicate card id in play")
        hand = self.hands[seat]
        drawn: list[PhysCard] = []
        for cid in cid_order:
            idx = next((i for i, c in enumerate(hand) if c.cid == cid), None)
            if idx is None:
                raise ValueError("card not in hand")
            drawn.append(hand.pop(idx))
        return tuple(drawn)

    def legal_combo_plays(self, seat: int) -> list[list[PhysCard]]:
        if self.phase != "play" or seat != self._to_act():
            return []
        trick_view = [(s, tuple(cs)) for s, cs in self.current_trick]
        return legal_plays_for_turn(self.trump, trick_view, self.hands[seat])

    def _attacker_seats_provisional(self) -> set[int]:
        """Current 庄方进攻席（6 人找朋友：庄 + 已揭牌朋友；否则对角）。"""

        if self.num_players == 6 and self.friend_calls:
            return {self.declarer_seat} | self._revealed_friend_seats
        return declarer_side_seats(self.declarer_seat, self.num_players)

    def _attacker_seats_final(self) -> set[int]:
        """终局计分用庄方。双友均揭晓且共三席时走 3v3，否则对角。"""

        atk = {self.declarer_seat} | self._revealed_friend_seats
        if self.num_players == 6 and len(self.friend_calls) == 2 and len(atk) == 3:
            return atk
        return declarer_side_seats(self.declarer_seat, self.num_players)

    def _to_act(self) -> int:
        if not self.current_trick:
            return self.leader
        return (self.leader + len(self.current_trick)) % self.num_players

    def play_cards(self, seat: int, card_ids: list[int]) -> dict:
        if self.phase != "play":
            raise ValueError("hand already scored")
        if seat != self._to_act():
            raise PermissionError("not your turn")
        if not card_ids:
            raise ValueError("no cards submitted")

        wanted = sorted(int(x) for x in card_ids)
        trick_so_far = [(s, tuple(cs)) for s, cs in self.current_trick]
        opts = legal_plays_for_turn(self.trump, trick_so_far, self.hands[seat])
        wf = frozenset(wanted)
        if wf not in {frozenset(c.cid for c in o) for o in opts}:
            raise ValueError("illegal combo")

        played_bundle = self._take_cards_ordered(seat, wanted)
        events: list[dict] = []
        self.current_trick.append((seat, played_bundle))

        if self.friend_tracker:
            for card in played_bundle:
                for ev in self.friend_tracker.observe(seat, card):
                    self._revealed_friend_seats.add(ev.reveal_seat)
                    events.append({"type": "friend_reveal", "nth": ev.call.nth, "seat": ev.reveal_seat})

        if len(self.current_trick) < self.num_players:
            return {"events": events}

        ws = combo_trick_winner_seat(self.trump, [(s, tuple(cs)) for s, cs in self.current_trick])
        points_this_trick = sum(point_value(c) for _s, cs in self.current_trick for c in cs)
        atk_now = self._attacker_seats_provisional()
        record_plays = tuple((s, tuple(cs)) for s, cs in self.current_trick)
        defenders_gained = ws not in atk_now
        record = CompletedTrickRecord(
            winner_seat=ws,
            trick_points=points_this_trick,
            defenders_gained=defenders_gained,
            plays=record_plays,
        )
        self._completed_tricks.append(record)

        events.append(
            {
                "type": "trick_done",
                "winner_seat": ws,
                "trick_points": points_this_trick,
                "defenders_gained_this_trick": defenders_gained,
            }
        )

        self.leader = ws
        self.trick_index += 1
        self.current_trick.clear()

        if all(len(h) == 0 for h in self.hands):
            self._finalize_scoring(ws)
            events.extend(self._finalize_events_snapshot())

        return {"events": events}

    def _finalize_scoring(self, last_trick_winner: int) -> None:
        th = defenders_threshold(self.num_players)
        atk = self._attacker_seats_final()
        trick_part = sum(r.trick_points for r in self._completed_tricks if r.winner_seat not in atk)

        kp = points_in_cards(self.kitty)
        last_trick = self._completed_tricks[-1]
        lead_cards = last_trick.plays[0][1]
        mult = kitty_multiplier_for_last_trick(num_cards_in_leading_combo=len(lead_cards))
        bonus_base = kp * mult

        kitty_bonus = 0
        if last_trick_winner not in atk:
            kitty_bonus += bonus_base

        defender_final = trick_part + kitty_bonus

        self.phase = "scored"
        self.result = HandResult(
            defender_points_final=defender_final,
            defender_points_tricks_only=trick_part,
            kitty_bonus_to_defenders=kitty_bonus,
            last_trick_winner=last_trick_winner,
            level_breakdown=level_change_after_deal(defender_final, th),
            declarer_seat=self.declarer_seat,
        )

    def _finalize_events_snapshot(self) -> list[dict]:
        if self.result is None:
            return []
        return [
            {
                "type": "hand_over",
                "level_change": self.result.level_breakdown,
                "summary": defender_summary(self.result),
            },
        ]


def defender_summary(res: HandResult) -> dict:
    return {
        "defender_points_final": res.defender_points_final,
        "defender_points_tricks_only": res.defender_points_tricks_only,
        "kitty_bonus_to_defenders": res.kitty_bonus_to_defenders,
    }
