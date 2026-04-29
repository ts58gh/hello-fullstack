"""Trump / 主 classification and per-trick ordering for 升级."""

from __future__ import annotations

from dataclasses import dataclass

from .cards import JokerFace, PhysCard, RegularFace, Suit


@dataclass(frozen=True)
class TrumpContext:
    """Immutable description of trumps for one deal."""

    level_rank: int
    trump_suit: Suit | None

    def __post_init__(self) -> None:
        if self.level_rank not in range(2, 15):
            raise ValueError("level_rank must be 2..14 (2..A)")


def is_level_card(ctx: TrumpContext, c: PhysCard) -> bool:
    if isinstance(c.face, JokerFace):
        return False
    rf = c.face
    assert isinstance(rf, RegularFace)
    return rf.rank == ctx.level_rank


def is_trump(ctx: TrumpContext, c: PhysCard) -> bool:
    """Whether ``c`` is classified as 主 for follow / lead rules."""

    if isinstance(c.face, JokerFace):
        return True
    rf = c.face
    assert isinstance(rf, RegularFace)
    if ctx.trump_suit is None:
        # 无主: level cards + both jokers trump; others are 副.
        return is_level_card(ctx, c)
    return is_level_card(ctx, c) or rf.suit == ctx.trump_suit


def _cat(ctx: TrumpContext, c: PhysCard) -> int:
    """Absolute category: higher number beats lower (for single-card resolution)."""

    if isinstance(c.face, JokerFace):
        return 6 if c.face.big else 5
    rf = c.face
    assert isinstance(rf, RegularFace)

    if ctx.trump_suit is None:
        # 无主: level cards share one bucket; everything else is lowest.
        return 4 if rf.rank == ctx.level_rank else 1

    tr = ctx.trump_suit
    if rf.suit == tr and rf.rank == ctx.level_rank:
        return 4  # main-suit level cards
    if rf.rank == ctx.level_rank and rf.suit != tr:
        return 3  # off-suit level cards
    if rf.suit == tr:
        return 2  # non-level trumps in trump suit
    return 1


def strength_key(ctx: TrumpContext, c: PhysCard, *, play_index: int) -> tuple:
    """Comparable key for comparisons within a single trick (**singles** only).

    Tie-break: **先出者大** — smaller ``play_index`` wins when all else equal
    (represented as last tuple field ``-play_index`` so that *larger* tuple wins).
    """

    cat = _cat(ctx, c)
    tie = -play_index  # first to play wins absolute ties

    if isinstance(c.face, JokerFace):
        return (cat, 0, 0, tie)

    rf = c.face
    assert isinstance(rf, RegularFace)

    if cat == 4:
        return (cat, 0, 0, tie)
    if cat == 3:
        return (cat, 0, 0, tie)

    return (cat, rf.rank, rf.suit.value, tie)


def compare_single_trick_winner(
    ctx: TrumpContext,
    plays: list[tuple[int, PhysCard]],
) -> int:
    """Return winning *seat index*. ``plays[k] = (seat, card)`` ordered by trick."""

    best_seat, best_key = plays[0][0], strength_key(ctx, plays[0][1], play_index=0)
    for i, (seat, card) in enumerate(plays):
        k = strength_key(ctx, card, play_index=i)
        if k > best_key:
            best_key, best_seat = k, seat
    return best_seat
