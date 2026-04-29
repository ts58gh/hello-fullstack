from app.sheng.cards import PhysCard, RegularFace, Suit
from app.sheng.friend import FriendCall, FriendPlayTracker


def _make_card(suit: Suit, rank: int, cid: int) -> PhysCard:
    return PhysCard(cid, RegularFace(suit=suit, rank=rank))


def test_friend_tracker_second_spade_ace():
    calls = (FriendCall(2, Suit.SPADES, 14),)  # 2nd ♠A
    tr = FriendPlayTracker(calls)
    a1 = _make_card(Suit.SPADES, 14, 0)
    a2 = _make_card(Suit.SPADES, 14, 1)
    assert tr.observe(0, a1) == []
    ev = tr.observe(3, a2)
    assert len(ev) == 1
    assert ev[0].reveal_seat == 3
