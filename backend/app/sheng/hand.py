"""Run one finished 升级 hand (multi-card combos: single / pair / triple / plain tractor).

First trick opens with **庄家领出**. After 叫主, the successful bidder becomes
``declarer_seat`` and opens; if nobody called, 庄 stays the opening banker and

``leader=(bank+1)%n`` (**庄家下手**).


Six-player **找朋友**：可声明两张朋友牌（揭牌由 :mod:`friend` 跟踪）。
若本副 **两张朋友牌均已揭牌** 且与庄家共 **三** 个不同座位，则 **捡分 / 底牌奖** 按 **3v3**（庄方 vs 三门）计算；否则 **回退为对角两队**。

Kitty stays aside until scoring: defenders add ``kitty_multiplier × kitty_points``
to their tally **only when a defender-seat player wins the last trick**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .cards import JokerFace, PhysCard, RegularFace, Suit, build_shoe, deal, shoe_size_for_players
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
    declare_stakes_bonus: int
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


DECLARE_SUIT_ORDER: dict[str, int] = {"C": 0, "D": 1, "H": 2, "S": 3}
# Suited keys use (tier, suit_ordinal). NT is top. Same tier: higher suit ordinal wins.
_DECLARE_TIER_PLAIN = 550
_DECLARE_TIER_SJ = 620
_DECLARE_TIER_BJ = 690
_DECLARE_TIER_PAIR = 760
DECLARE_NT_KEY: tuple[int, ...] = (900,)

_DECLARE_LINE_STAKE = {"plain": 6, "sj": 14, "bj": 22, "pair": 32, "nt": 42}
_DECLARE_ANTI_EACH = 8  # 反主加收：压过上一轮叫品时记入闲家加成


@dataclass
class RunningHand:
    num_players: int
    seed: int | None
    declarer_seat: int
    match_level_rank: int
    trump_suit: Suit | None
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
    declare_to_act_seat: int = 0
    declare_passes_since_change: int = 0
    declare_best_key: tuple[int, ...] = (-1,)
    opening_bank_seat: int = 0
    declare_winner_seat: int | None = None
    declare_stakes: int = 0
    phase: Literal["declare", "play", "scored"] = "declare"
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
        match_level_rank: int = 2,
        friend_calls: tuple[FriendCall, ...] = (),
    ) -> "RunningHand":
        if num_players not in (4, 6):
            raise ValueError("num_players must be 4 or 6")
        nd = shoe_size_for_players(num_players)
        shoe = build_shoe(nd)
        hands_t, kitty = deal(shoe, num_players, seed=seed)
        # Provisional hearts until declare ends (all-pass → Hearts); bid may set suit or NT.
        provisional = Suit.HEARTS
        trump = TrumpContext(level_rank=match_level_rank, trump_suit=provisional)
        fc_tuple = tuple(friend_calls)
        tracker = FriendPlayTracker(fc_tuple) if fc_tuple else None
        base = declarer_seat % num_players
        leader = (base + 1) % num_players
        declare_open = leader
        return cls(
            num_players=num_players,
            seed=seed,
            declarer_seat=base,
            match_level_rank=match_level_rank,
            trump_suit=provisional,
            hands=list(map(list, hands_t)),
            kitty=list(kitty),
            trump=trump,
            leader=leader,
            friend_tracker=tracker,
            friend_calls=fc_tuple,
            declare_to_act_seat=declare_open,
            declare_passes_since_change=0,
            declare_best_key=(-1,),
            opening_bank_seat=base,
            declare_winner_seat=None,
            declare_stakes=0,
            phase="declare",
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

    def _declare_suit_strength(self, suit: Suit) -> int:
        return DECLARE_SUIT_ORDER[suit.value]

    def _level_cards_in_suit_count(self, seat: int, suit: Suit) -> int:
        n = 0
        for c in self.hands[seat]:
            face = c.face
            if isinstance(face, RegularFace) and face.rank == self.match_level_rank and face.suit == suit:
                n += 1
        return n

    def _hand_has_level_card_in_suit(self, seat: int, suit: Suit) -> bool:
        return self._level_cards_in_suit_count(seat, suit) >= 1

    def _hand_has_sj(self, seat: int) -> bool:
        return any(isinstance(c.face, JokerFace) and not c.face.big for c in self.hands[seat])

    def _hand_has_bj(self, seat: int) -> bool:
        return any(isinstance(c.face, JokerFace) and c.face.big for c in self.hands[seat])

    def _hand_has_both_jokers(self, seat: int) -> bool:
        return self._hand_has_sj(seat) and self._hand_has_bj(seat)

    def _key_plain(self, suit: Suit) -> tuple[int, ...]:
        return (_DECLARE_TIER_PLAIN, self._declare_suit_strength(suit))

    def _key_sj(self, suit: Suit) -> tuple[int, ...]:
        return (_DECLARE_TIER_SJ, self._declare_suit_strength(suit))

    def _key_bj(self, suit: Suit) -> tuple[int, ...]:
        return (_DECLARE_TIER_BJ, self._declare_suit_strength(suit))

    def _key_pair(self, suit: Suit) -> tuple[int, ...]:
        return (_DECLARE_TIER_PAIR, self._declare_suit_strength(suit))

    def _add_stakes(self, line: str) -> int:
        is_counter = self.declare_best_key != (-1,)
        delta = _DECLARE_LINE_STAKE[line]
        if is_counter:
            delta += _DECLARE_ANTI_EACH
        self.declare_stakes += delta
        return delta

    def _apply_winning_declare(
        self,
        seat: int,
        new_key: tuple[int, ...],
        line: str,
        events: list[dict[str, Any]],
        **kv: Any,
    ) -> None:
        if not (new_key > self.declare_best_key):
            raise ValueError("bid does not beat current main")
        delta = self._add_stakes(line)
        self.declare_best_key = new_key
        self.declare_winner_seat = seat
        self.declare_passes_since_change = 0
        events.append(
            {
                "type": "declare_bid",
                "seat": seat,
                **kv,
                "declare_stakes_now": self.declare_stakes,
                "stakes_added": delta,
                "bid_key": list(new_key),
            }
        )

    def legal_declare_options(self, seat: int) -> list[dict[str, Any]]:
        if self.phase != "declare" or seat != self.declare_to_act_seat:
            return []
        out: list[dict[str, Any]] = [{"kind": "pass"}]
        bk = self.declare_best_key
        for suit in (Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES):
            lc = self._level_cards_in_suit_count(seat, suit)
            if lc >= 2 and self._key_pair(suit) > bk:
                out.append({"kind": "bid_pair", "suit": suit.value})
            if lc >= 1:
                has_sj = self._hand_has_sj(seat)
                has_bj = self._hand_has_bj(seat)
                if self._key_plain(suit) > bk:
                    out.append({"kind": "bid_plain", "suit": suit.value})
                if has_sj and self._key_sj(suit) > bk:
                    out.append({"kind": "bid_sj", "suit": suit.value})
                if has_bj and self._key_bj(suit) > bk:
                    out.append({"kind": "bid_bj", "suit": suit.value})
        if self._hand_has_both_jokers(seat) and DECLARE_NT_KEY > bk:
            out.append({"kind": "bid_nt"})
        return out

    def _finish_declare_phase(self, events_out: list[dict[str, Any]]) -> None:
        if self.phase != "declare":
            return
        if self.declare_best_key == (-1,):
            bank = self.opening_bank_seat % self.num_players
            self.declarer_seat = bank
            self.trump_suit = Suit.HEARTS
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=Suit.HEARTS)
            self.leader = (bank + 1) % self.num_players
            self.declare_winner_seat = None
        else:
            ws = self.declare_winner_seat
            assert ws is not None
            self.declarer_seat = ws % self.num_players
            self.leader = self.declarer_seat
        self.phase = "play"
        ts = None if self.trump_suit is None else self.trump_suit.value
        events_out.append(
            {
                "type": "declare_done",
                "trump_suit": ts,
                "declarer_seat": self.declarer_seat,
                "leader": self.leader,
                "declare_stakes": self.declare_stakes,
            }
        )

    def declare_submit(self, seat: int, payload: dict[str, Any]) -> dict[str, Any]:
        if self.phase != "declare":
            raise ValueError("not in declare phase")
        if seat != self.declare_to_act_seat:
            raise PermissionError("not your turn to declare")

        raw = payload.get("action") or payload.get("kind") or ""
        action = str(raw).lower().replace("-", "_")
        events: list[dict[str, Any]] = []

        if action in ("pass",):
            self.declare_passes_since_change += 1
            events.append({"type": "declare_pass", "seat": seat})
        elif action in ("bid_suit", "bid_plain"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit(seat, suit):
                raise ValueError("no playable level-card in this suit")
            nk = self._key_plain(suit)
            self._apply_winning_declare(seat, nk, "plain", events, trump_suit=suit.value, bid_kind="plain")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
        elif action in ("bid_sj", "bid_suit_sj"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit(seat, suit) or not self._hand_has_sj(seat):
                raise ValueError("needs level card + small joker")
            nk = self._key_sj(suit)
            self._apply_winning_declare(seat, nk, "sj", events, trump_suit=suit.value, bid_kind="sj")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
        elif action in ("bid_bj", "bid_suit_bj"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit(seat, suit) or not self._hand_has_bj(seat):
                raise ValueError("needs level card + big joker")
            nk = self._key_bj(suit)
            self._apply_winning_declare(seat, nk, "bj", events, trump_suit=suit.value, bid_kind="bj")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
        elif action in ("bid_pair",):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if self._level_cards_in_suit_count(seat, suit) < 2:
                raise ValueError("need pair of level cards in suit")
            nk = self._key_pair(suit)
            self._apply_winning_declare(seat, nk, "pair", events, trump_suit=suit.value, bid_kind="pair")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
        elif action in ("bid_nt", "nt", "no_trump"):
            if not self._hand_has_both_jokers(seat):
                raise ValueError("无主 requires big and small joker")
            self._apply_winning_declare(seat, DECLARE_NT_KEY, "nt", events, trump_suit=None, bid_kind="nt")
            self.trump_suit = None
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=None)
        else:
            raise ValueError("unknown declare action")

        if self.declare_passes_since_change >= self.num_players:
            self._finish_declare_phase(events)
        elif self.phase == "declare":
            self.declare_to_act_seat = (self.declare_to_act_seat + 1) % self.num_players

        return {"events": events}

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
            raise ValueError("not in play phase")
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

        stakes = int(self.declare_stakes)
        defender_final = trick_part + kitty_bonus + stakes

        self.phase = "scored"
        self.result = HandResult(
            defender_points_final=defender_final,
            defender_points_tricks_only=trick_part,
            kitty_bonus_to_defenders=kitty_bonus,
            declare_stakes_bonus=stakes,
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
        "declare_stakes_bonus": res.declare_stakes_bonus,
    }
