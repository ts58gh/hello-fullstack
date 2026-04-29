"""Play / follow rules (v1 — single-card leads only)."""

from __future__ import annotations

from .cards import JokerFace, PhysCard, RegularFace
from .trump import TrumpContext, compare_single_trick_winner, is_trump


def _is_plain_in_suit(ctx: TrumpContext, c: PhysCard, suit) -> bool:
    """True if ``c`` counts as a *副* card in natural ``suit`` (not 主)."""

    f = c.face
    if isinstance(f, JokerFace):
        return False
    assert isinstance(f, RegularFace)
    if f.suit != suit:
        return False
    # Even if literal suit matches, a card turned 主 cannot be used as plain follow.
    return not is_trump(ctx, c)


def follow_candidates_single(
    ctx: TrumpContext,
    led: PhysCard,
    hand: list[PhysCard],
) -> list[PhysCard]:
    """Return legal cards when following a leading single."""

    lf = led.face

    # Leading plain 副花色
    if isinstance(lf, RegularFace) and not is_trump(ctx, led):
        suit = lf.suit
        plain_same = [c for c in hand if _is_plain_in_suit(ctx, c, suit)]
        if plain_same:
            return plain_same
        return list(hand)  # 垫牌 — any card counts as discard

    # Leading anything considered 主
    mains = [c for c in hand if is_trump(ctx, c)]
    if mains:
        return mains
    return list(hand)


def trick_winner_seat_single(
    ctx: TrumpContext,
    tricks: list[tuple[int, PhysCard]],
) -> int:
    return compare_single_trick_winner(ctx, tricks)
