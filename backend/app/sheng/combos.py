"""Combinations: 对子 / 连对(拖拉机) / 刻子 — phase-1 subset.

Conservative tractors (副牌): same literal suit, natural consecutive ranks **without**
using level-ranked cards inside the plain-suit chain (those cards are tracked as 主).

级牌 arbitrary-suit pairing is implemented for **pairs / triples** only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .cards import JokerFace, PhysCard, RegularFace
from .trump import TrumpContext, is_level_card


class ComboKind(str, Enum):
    SINGLE = "single"
    PAIR = "pair"
    TRACTOR_PAIR = "tractor_pair"
    TRIPLE = "triple"
    DUMP = "dump"


@dataclass(frozen=True)
class ParsedCombo:
    kind: ComboKind
    cards: tuple[PhysCard, ...]


def _legal_pair(ctx: TrumpContext, a: PhysCard, b: PhysCard) -> bool:
    fa, fb = a.face, b.face
    if isinstance(fa, JokerFace) and isinstance(fb, JokerFace):
        return fa.big == fb.big
    if isinstance(fa, JokerFace) or isinstance(fb, JokerFace):
        return False
    assert isinstance(fa, RegularFace) and isinstance(fb, RegularFace)
    if is_level_card(ctx, a) and is_level_card(ctx, b):
        return fa.rank == fb.rank == ctx.level_rank
    return fa.suit == fb.suit and fa.rank == fb.rank


def _legal_triple(ctx: TrumpContext, triple: tuple[PhysCard, PhysCard, PhysCard]) -> bool:
    fa, fb, fc = triple[0].face, triple[1].face, triple[2].face
    if any(isinstance(x, JokerFace) for x in (fa, fb, fc)):
        return False
    assert isinstance(fa, RegularFace) and isinstance(fb, RegularFace) and isinstance(fc, RegularFace)
    a, b, c = triple
    if is_level_card(ctx, a) and is_level_card(ctx, b) and is_level_card(ctx, c):
        return fa.rank == fb.rank == fc.rank == ctx.level_rank
    return fa.suit == fb.suit == fc.suit and fa.rank == fb.rank == fc.rank


def parse_combo(ctx: TrumpContext, cards: list[PhysCard]) -> ParsedCombo:
    if not cards:
        raise ValueError("empty combo")
    n = len(cards)
    if n == 1:
        return ParsedCombo(ComboKind.SINGLE, (cards[0],))
    if n == 2:
        if not _legal_pair(ctx, cards[0], cards[1]):
            raise ValueError("not a legal pair")
        return ParsedCombo(ComboKind.PAIR, (cards[0], cards[1]))
    if n == 3:
        t = (cards[0], cards[1], cards[2])
        if not _legal_triple(ctx, t):
            raise ValueError("not a legal triple")
        return ParsedCombo(ComboKind.TRIPLE, t)
    if n % 2 == 0 and n >= 4 and _plain_suit_tractor(ctx, cards):
        return ParsedCombo(ComboKind.TRACTOR_PAIR, tuple(cards))
    raise ValueError("unsupported combo shape for v1 engine")


def parse_combo_relaxed(ctx: TrumpContext, cards: list[PhysCard]) -> ParsedCombo:
    """Like :func:`parse_combo`, but treat ill-shaped plays as DUMP (mixed-suit discard / follow)."""

    try:
        return parse_combo(ctx, cards)
    except ValueError:
        if not cards:
            raise ValueError("empty combo") from None
        return ParsedCombo(ComboKind.DUMP, tuple(cards))


def _plain_suit_tractor(ctx: TrumpContext, cards: list[PhysCard]) -> bool:
    """Tractor composed of consecutive natural pairs inside one literal side suit."""

    ctr: Counter[tuple[str, int]] = Counter()
    suits: set[str] = set()
    for c in cards:
        f = c.face
        if isinstance(f, JokerFace):
            return False
        assert isinstance(f, RegularFace)
        if is_level_card(ctx, c):
            # Plain-suit tractor cannot include current level-ranked cards — they are 主 elsewhere.
            return False
        suits.add(f.suit.value)
        ctr[(f.suit.value, f.rank)] += 1
    if len(suits) != 1:
        return False
    if any(v != 2 for v in ctr.values()):
        return False
    ranks = sorted({rk for (_s, rk) in ctr})
    if len(ranks) < 2:
        return False
    for a, b in zip(ranks, ranks[1:]):
        if b != a + 1:
            return False
    return True


def combo_summary(combo: ParsedCombo) -> str:
    if combo.kind == ComboKind.SINGLE:
        return combo.cards[0].label()
    return f"{combo.kind.value}:" + "+".join(c.label() for c in combo.cards)
