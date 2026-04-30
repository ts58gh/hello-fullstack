"""6 人找朋友终局 3v3 vs 对角回退。"""

from app.sheng.cards import Suit
from app.sheng.friend import FriendCall
from app.sheng.hand import RunningHand


def test_attacker_seats_final_uses_three_when_two_distinct_friends() -> None:
    fc = (
        FriendCall(1, Suit.SPADES, 14),
        FriendCall(2, Suit.HEARTS, 13),
    )
    rh = RunningHand.deal_new(num_players=6, seed=1, declarer_seat=0, friend_calls=fc)
    rh._revealed_friend_seats = {1, 3}
    assert rh._attacker_seats_final() == {0, 1, 3}


def test_attacker_seats_final_falls_back_when_only_one_friend_revealed() -> None:
    fc = (
        FriendCall(1, Suit.SPADES, 14),
        FriendCall(2, Suit.HEARTS, 13),
    )
    rh = RunningHand.deal_new(num_players=6, seed=1, declarer_seat=0, friend_calls=fc)
    rh._revealed_friend_seats = {1}
    assert rh._attacker_seats_final() == {0, 3}


def test_six_no_friend_calls_uses_diagonal() -> None:
    rh = RunningHand.deal_new(num_players=6, seed=1, declarer_seat=0, friend_calls=())
    assert rh._attacker_seats_final() == {0, 3}


def test_revealed_friend_seats_sorted_public_property() -> None:
    fc = (
        FriendCall(1, Suit.SPADES, 14),
        FriendCall(2, Suit.HEARTS, 13),
    )
    rh = RunningHand.deal_new(num_players=6, seed=1, declarer_seat=0, friend_calls=fc)
    rh._revealed_friend_seats = {5, 1}
    assert rh.revealed_friend_seats == (1, 5)
