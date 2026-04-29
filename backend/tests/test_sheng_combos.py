from app.sheng.cards import PhysCard, RegularFace, Suit
from app.sheng.combos import ComboKind, parse_combo
from app.sheng.trump import TrumpContext


def _c(suit: Suit, rank: int, cid: int) -> PhysCard:
    return PhysCard(cid, RegularFace(suit=suit, rank=rank))


def test_level_pair_mixed_suits():
    ctx = TrumpContext(level_rank=7, trump_suit=Suit.HEARTS)
    a = _c(Suit.CLUBS, 7, 0)
    b = _c(Suit.DIAMONDS, 7, 1)
    combo = parse_combo(ctx, [a, b])
    assert combo.kind == ComboKind.PAIR


def test_plain_tractor():
    ctx = TrumpContext(level_rank=7, trump_suit=Suit.HEARTS)
    # plain ♣9-♣10 tractor (four cards) — level 7 not on ♣ for these ranks
    cards = [
        _c(Suit.CLUBS, 9, 0),
        _c(Suit.CLUBS, 9, 1),
        _c(Suit.CLUBS, 10, 2),
        _c(Suit.CLUBS, 10, 3),
    ]
    combo = parse_combo(ctx, cards)
    assert combo.kind == ComboKind.TRACTOR_PAIR
