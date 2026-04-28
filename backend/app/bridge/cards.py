"""Cards and decks.

Cards are immutable (frozen dataclass) and hashable so they can live in sets.
Ranks use 2..14 (J=11, Q=12, K=13, A=14) so we can compare with simple ints.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Suit(str, Enum):
    CLUBS = "C"
    DIAMONDS = "D"
    HEARTS = "H"
    SPADES = "S"


SUIT_ORDER = [Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES]
SUIT_SYMBOL = {Suit.CLUBS: "\u2663", Suit.DIAMONDS: "\u2666", Suit.HEARTS: "\u2665", Suit.SPADES: "\u2660"}
RANK_LABEL = {11: "J", 12: "Q", 13: "K", 14: "A"}


def rank_label(rank: int) -> str:
    return RANK_LABEL.get(rank, str(rank))


@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: int  # 2..14

    def __post_init__(self) -> None:
        if not 2 <= self.rank <= 14:
            raise ValueError(f"invalid rank {self.rank}")

    @property
    def label(self) -> str:
        return f"{rank_label(self.rank)}{self.suit.value}"

    def to_dict(self) -> dict:
        return {"suit": self.suit.value, "rank": self.rank, "label": self.label}


def full_deck() -> list[Card]:
    return [Card(s, r) for s in SUIT_ORDER for r in range(2, 15)]


def deal_hands(seed: int | None = None) -> dict[str, list[Card]]:
    """Shuffle a fresh deck and deal 13 cards to each of N/E/S/W.

    Returns a dict keyed by seat letter for friendliness; callers convert to
    Seat enum if they want.
    """
    rng = random.Random(seed)
    deck = full_deck()
    rng.shuffle(deck)
    return {
        "N": deck[0:13],
        "E": deck[13:26],
        "S": deck[26:39],
        "W": deck[39:52],
    }


def sort_hand(cards: list[Card]) -> list[Card]:
    """Display order: spades, hearts, diamonds, clubs (alternating colors), high to low."""
    display_order = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]
    out: list[Card] = []
    for s in display_order:
        out.extend(sorted([c for c in cards if c.suit == s], key=lambda c: -c.rank))
    return out


def hcp(cards: list[Card]) -> int:
    """High-card points (Milton Work): A=4, K=3, Q=2, J=1."""
    table = {14: 4, 13: 3, 12: 2, 11: 1}
    return sum(table.get(c.rank, 0) for c in cards)
