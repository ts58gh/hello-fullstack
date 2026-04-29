"""Physical decks for 升级 (standard 54-card pack × N — N=2 gives 108, N=3 gives 162).

Each dealt card carries a globally unique integer ``cid`` within the shoe so
that duplicate ♠As can be distinguished (needed for 找 friends: "`第 N 张 ♠A`").
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Suit(str, Enum):
    CLUBS = "C"
    DIAMONDS = "D"
    HEARTS = "H"
    SPADES = "S"


# Numeric ranks 2..14 (2 low .. A high) — matches classic Python bridge-style ordering.
RANK_TWO = 2
RANK_ACE = 14
ALL_RANKS: tuple[int, ...] = tuple(range(RANK_TWO, RANK_ACE + 1))

SUITS_ROT: tuple[Suit, ...] = (Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS)


def rank_symbol(rank: int) -> str:
    if rank == 14:
        return "A"
    if rank == 13:
        return "K"
    if rank == 12:
        return "Q"
    if rank == 11:
        return "J"
    if rank == 10:
        return "10"
    if rank == 2:
        return "2"
    return str(rank)


@dataclass(frozen=True)
class RegularFace:
    suit: Suit
    rank: int

    def __post_init__(self) -> None:
        if self.rank not in ALL_RANKS:
            raise ValueError(f"illegal rank {self.rank}")

    def label(self) -> str:
        return f"{rank_symbol(self.rank)}{self.suit.value}"


@dataclass(frozen=True)
class JokerFace:
    big: bool  # False = small

    def label(self) -> str:
        return "BJ" if self.big else "SJ"


Face = RegularFace | JokerFace


@dataclass(frozen=True)
class PhysCard:
    """One physical occurrence in the shoe."""

    cid: int
    face: Face

    @property
    def is_joker(self) -> bool:
        return isinstance(self.face, JokerFace)

    def label(self) -> str:
        return self.face.label()

    def to_dict(self) -> dict:
        if isinstance(self.face, RegularFace):
            return {"cid": self.cid, "kind": "regular", "suit": self.face.suit.value, "rank": self.face.rank}
        fj = self.face
        assert isinstance(fj, JokerFace)
        return {"cid": self.cid, "kind": "bj" if fj.big else "sj"}


def _one_standard_54_cards(start_cid: int) -> tuple[list[PhysCard], int]:
    out: list[PhysCard] = []
    cid = start_cid
    for suit in SUITS_ROT:
        for rk in ALL_RANKS:
            out.append(PhysCard(cid, RegularFace(suit=suit, rank=rk)))
            cid += 1
    out.append(PhysCard(cid, JokerFace(big=False)))
    cid += 1
    out.append(PhysCard(cid, JokerFace(big=True)))
    cid += 1
    return out, cid


def build_shoe(num_decks: int) -> list[PhysCard]:
    """Return ``num_decks`` standard 54-card packs concatenated with unique cids."""
    if num_decks < 1:
        raise ValueError("num_decks must be >= 1")
    out: list[PhysCard] = []
    cid = 0
    for _ in range(num_decks):
        chunk, cid = _one_standard_54_cards(cid)
        out.extend(chunk)
    return out


def shoe_size_for_players(num_players: int) -> int:
    if num_players == 4:
        return 2
    if num_players == 6:
        return 3
    raise ValueError("only 4 or 6 players supported in v1")


def cards_per_player(num_players: int) -> int:
    return 25


def kitty_size(num_players: int) -> int:
    if num_players == 4:
        return 8
    if num_players == 6:
        return 12
    raise ValueError("only 4 or 6 players supported in v1")


def deal(
    shoe: list[PhysCard],
    num_players: int,
    *,
    seed: int | None = None,
) -> tuple[list[list[PhysCard]], list[PhysCard]]:
    """Shuffle ``shoe`` and deal ``cards_per_player`` to each seat in order.

    Seats are indexed 0..num_players-1 clockwise. Remaining cards are the kitty.
    """
    n = num_players
    if n not in (4, 6):
        raise ValueError("only 4 or 6 players supported in v1")
    per = cards_per_player(n)
    need = n * per + kitty_size(n)
    if len(shoe) != need:
        raise ValueError(f"shoe has {len(shoe)} cards, expected {need} for {n} players")
    deck = list(shoe)
    rng = random.Random(seed)
    rng.shuffle(deck)
    hands: list[list[PhysCard]] = [[] for _ in range(n)]
    for i, card in enumerate(deck[: n * per]):
        hands[i % n].append(card)
    kitty = deck[n * per :]
    return hands, kitty


def sort_hand_display(cards: list[PhysCard]) -> list[PhysCard]:
    """Sort for UI: jokers last, then by suit order, then rank high→low."""

    def key(c: PhysCard) -> tuple:
        if isinstance(c.face, JokerFace):
            return (2, 1 if c.face.big else 0, c.cid)
        rf = c.face
        assert isinstance(rf, RegularFace)
        # Group by suit order in SUITS_ROT
        try:
            si = SUITS_ROT.index(rf.suit)
        except ValueError:
            si = 99
        return (0, si, -rf.rank, c.cid)

    return sorted(cards, key=key)
