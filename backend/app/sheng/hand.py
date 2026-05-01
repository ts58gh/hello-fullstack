"""Run one finished 升级 hand (multi-card combos: single / pair / triple / plain tractor).

First trick opens with **庄家领出**. After 叫主, the successful bidder becomes
``declarer_seat`` and opens; if nobody called, 庄 stays the opening banker and

``leader=(bank+1)%n`` (**庄家下手**).


Six-player **找朋友**：可声明两张朋友牌（揭牌由 :mod:`friend` 跟踪）。
若本副 **两张朋友牌均已揭牌** 且与庄家共 **三** 个不同座位，则 **捡分 / 底牌奖** 按 **3v3**（庄方 vs 三门）计算；否则 **回退为对角两队**。

Kitty stays aside until scoring: declarer **merged kitty into hand**, then chooses
the same count to **bury** as the scoring pile for the hand; defenders add
``kitty_multiplier × kitty_points``
to their tally **only when a defender-seat player wins the last trick**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .cards import (
    JokerFace,
    PhysCard,
    RegularFace,
    Suit,
    build_shoe,
    deal,
    kitty_size,
    shoe_size_for_players,
)
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
    _deal_flat: tuple[PhysCard, ...]
    deal_reveal_steps: int
    bury_card_count: int
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
    phase: Literal["declare", "kitty", "play", "scored"] = "declare"
    declare_history: list[dict[str, Any]] = field(default_factory=list)
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
        hands_t, kitty, deal_flat = deal(shoe, num_players, seed=seed)
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
            _deal_flat=deal_flat,
            deal_reveal_steps=0,
            bury_card_count=0,
            declare_history=[],
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

    def _visible_cards(self, seat: int) -> list[PhysCard]:
        n = self.num_players
        R = max(0, min(self.deal_reveal_steps, len(self._deal_flat)))
        return [self._deal_flat[j] for j in range(R) if j % n == seat]

    def reveal_full_deal(self) -> None:
        """Expose every dealt player card (testing or instant-reveal clients)."""

        self.deal_reveal_steps = len(self._deal_flat)

    def advance_deal_step(self, steps: int = 1) -> list[dict[str, Any]]:
        if self.phase != "declare":
            raise ValueError("deal can only advance during declare phase")
        mx = len(self._deal_flat)
        prev = self.deal_reveal_steps
        self.deal_reveal_steps = max(0, min(mx, prev + max(0, int(steps))))
        return [
            {
                "type": "deal_advanced",
                "deal_reveal_steps": self.deal_reveal_steps,
                "deal_total_steps": mx,
            }
        ]

    def bury_submit(self, seat: int, card_ids: list[int]) -> dict[str, Any]:
        if self.phase != "kitty":
            raise ValueError("not in kitty bury phase")
        if seat != self.declarer_seat:
            raise PermissionError("only declarer buries the kitty")
        k = self.bury_card_count
        if k <= 0:
            raise ValueError("invalid bury count")
        wanted = sorted(int(x) for x in card_ids)
        if len(wanted) != len(set(wanted)) or len(wanted) != k:
            raise ValueError(f"must bury exactly {k} distinct cards from hand")
        bundle = list(self._take_cards_ordered(seat, wanted))
        self.kitty = sorted(bundle, key=lambda c: c.cid)
        self.phase = "play"
        self.bury_card_count = 0
        ev_bury = {"type": "bury_done", "seat": seat, "card_count": len(self.kitty)}
        self.declare_history.append({"kind": "bury_done", "seat": seat, "bury_count": len(self.kitty)})
        return {"events": [ev_bury]}

    def _pile_for_declare_checks(self, seat: int) -> list[PhysCard]:
        """Cards this seat may use to declare (progressive deal = visible subset)."""

        return self._visible_cards(seat)

    def _level_cards_in_suit_count(self, seat: int, suit: Suit) -> int:
        return self._level_cards_in_suit_from(self.hands[seat], suit)

    @staticmethod
    def _level_cards_in_suit_from(pile: list[PhysCard], suit: Suit, *, match_rank: int) -> int:
        n = 0
        for c in pile:
            face = c.face
            if isinstance(face, RegularFace) and face.rank == match_rank and face.suit == suit:
                n += 1
        return n

    def _hand_has_level_card_in_suit_from(self, pile: list[PhysCard], suit: Suit) -> bool:
        return (
            RunningHand._level_cards_in_suit_from(pile, suit, match_rank=self.match_level_rank) >= 1
        )

    @staticmethod
    def _pile_has_sj(pile: list[PhysCard]) -> bool:
        return any(isinstance(c.face, JokerFace) and not c.face.big for c in pile)

    @staticmethod
    def _pile_has_bj(pile: list[PhysCard]) -> bool:
        return any(isinstance(c.face, JokerFace) and c.face.big for c in pile)

    @staticmethod
    def _pile_has_both_jokers(pile: list[PhysCard]) -> bool:
        return RunningHand._pile_has_sj(pile) and RunningHand._pile_has_bj(pile)

    def _declare_suit_strength(self, suit: Suit) -> int:
        return DECLARE_SUIT_ORDER[suit.value]

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
        mat = self._pile_for_declare_checks(seat)
        out: list[dict[str, Any]] = [{"kind": "pass"}]
        bk = self.declare_best_key
        mr = self.match_level_rank
        for suit in (Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES):
            lc = RunningHand._level_cards_in_suit_from(mat, suit, match_rank=mr)
            if lc >= 2 and self._key_pair(suit) > bk:
                out.append({"kind": "bid_pair", "suit": suit.value})
            if lc >= 1:
                has_sj = RunningHand._pile_has_sj(mat)
                has_bj = RunningHand._pile_has_bj(mat)
                if self._key_plain(suit) > bk:
                    out.append({"kind": "bid_plain", "suit": suit.value})
                if has_sj and self._key_sj(suit) > bk:
                    out.append({"kind": "bid_sj", "suit": suit.value})
                if has_bj and self._key_bj(suit) > bk:
                    out.append({"kind": "bid_bj", "suit": suit.value})
        if RunningHand._pile_has_both_jokers(mat) and DECLARE_NT_KEY > bk:
            out.append({"kind": "bid_nt"})
        return out

    def _finish_declare_phase(self, events_out: list[dict[str, Any]]) -> None:
        if self.phase != "declare":
            return
        self.deal_reveal_steps = len(self._deal_flat)
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
        kz = kitty_size(self.num_players)
        self.bury_card_count = kz
        self.hands[self.declarer_seat].extend(self.kitty)
        self.kitty = []
        self.phase = "kitty"
        ts = None if self.trump_suit is None else self.trump_suit.value
        done_ev = {
            "type": "declare_done",
            "trump_suit": ts,
            "declarer_seat": self.declarer_seat,
            "leader": self.leader,
            "declare_stakes": self.declare_stakes,
            "bury_card_count": kz,
        }
        events_out.append(done_ev)
        self.declare_history.append(
            {
                "kind": "declare_done",
                "trump_suit": ts,
                "declarer_seat": self.declarer_seat,
                "leader": self.leader,
                "bury_card_count": kz,
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

        mat = self._pile_for_declare_checks(seat)

        if action in ("pass",):
            self.declare_passes_since_change += 1
            events.append({"type": "declare_pass", "seat": seat})
            self.declare_history.append({"kind": "pass", "seat": seat})
        elif action in ("bid_suit", "bid_plain"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit_from(mat, suit):
                raise ValueError("no playable level-card in this suit")
            nk = self._key_plain(suit)
            self._apply_winning_declare(seat, nk, "plain", events, trump_suit=suit.value, bid_kind="plain")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
            self.declare_history.append({"kind": "bid", "seat": seat, "bid_kind": "plain", "suit": suit.value})
        elif action in ("bid_sj", "bid_suit_sj"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit_from(mat, suit) or not RunningHand._pile_has_sj(mat):
                raise ValueError("needs level card + small joker")
            nk = self._key_sj(suit)
            self._apply_winning_declare(seat, nk, "sj", events, trump_suit=suit.value, bid_kind="sj")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
            self.declare_history.append({"kind": "bid", "seat": seat, "bid_kind": "sj", "suit": suit.value})
        elif action in ("bid_bj", "bid_suit_bj"):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            if not self._hand_has_level_card_in_suit_from(mat, suit) or not RunningHand._pile_has_bj(mat):
                raise ValueError("needs level card + big joker")
            nk = self._key_bj(suit)
            self._apply_winning_declare(seat, nk, "bj", events, trump_suit=suit.value, bid_kind="bj")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
            self.declare_history.append({"kind": "bid", "seat": seat, "bid_kind": "bj", "suit": suit.value})
        elif action in ("bid_pair",):
            suit_v = payload.get("suit")
            if suit_v is None:
                raise ValueError("suit required")
            suit = Suit(str(suit_v))
            mr = self.match_level_rank
            if RunningHand._level_cards_in_suit_from(mat, suit, match_rank=mr) < 2:
                raise ValueError("need pair of level cards in suit")
            nk = self._key_pair(suit)
            self._apply_winning_declare(seat, nk, "pair", events, trump_suit=suit.value, bid_kind="pair")
            self.trump_suit = suit
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=suit)
            self.declare_history.append({"kind": "bid", "seat": seat, "bid_kind": "pair", "suit": suit.value})
        elif action in ("bid_nt", "nt", "no_trump"):
            if not RunningHand._pile_has_both_jokers(mat):
                raise ValueError("无主 requires big and small joker")
            self._apply_winning_declare(seat, DECLARE_NT_KEY, "nt", events, trump_suit=None, bid_kind="nt")
            self.trump_suit = None
            self.trump = TrumpContext(level_rank=self.match_level_rank, trump_suit=None)
            self.declare_history.append({"kind": "bid", "seat": seat, "bid_kind": "nt"})
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
