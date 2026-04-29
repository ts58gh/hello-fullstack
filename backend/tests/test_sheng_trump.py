from app.sheng.cards import PhysCard, JokerFace, RegularFace, Suit
from app.sheng.trump import TrumpContext, compare_single_trick_winner


def _r(suit: Suit, rank: int, cid: int) -> PhysCard:
    return PhysCard(cid, RegularFace(suit=suit, rank=rank))


def _j(big: bool, cid: int) -> PhysCard:
    return PhysCard(cid, JokerFace(big=big))


def test_big_joker_beats_small():
    ctx = TrumpContext(level_rank=9, trump_suit=Suit.HEARTS)
    plays = [(0, _j(False, 0)), (1, _j(True, 1))]
    assert compare_single_trick_winner(ctx, plays) == 1


def test_off_suit_level_tie_first_wins():
    ctx = TrumpContext(level_rank=8, trump_suit=Suit.HEARTS)
    a = _r(Suit.CLUBS, 8, 0)
    b = _r(Suit.DIAMONDS, 8, 1)
    plays = [(0, a), (1, b)]
    # same category; first play should win absolute tie
    assert compare_single_trick_winner(ctx, plays) == 0
