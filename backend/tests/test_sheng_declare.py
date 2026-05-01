"""叫主 MVP: pass chain ends deal; suit / 无主 bids require material in hand."""

from app.sheng.cards import Suit
from app.sheng.hand import RunningHand
from app.sheng.trump import TrumpContext


def _autopass_until_play(rh: RunningHand) -> None:
    while rh.phase == "declare":
        s = rh.declare_to_act_seat
        rh.declare_submit(s, {"action": "pass"})


def test_all_pass_defaults_hearts_then_play_phase() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=999, declarer_seat=0, match_level_rank=7)
    assert rh.phase == "declare"
    _autopass_until_play(rh)
    assert rh.phase == "play"
    assert rh.trump == TrumpContext(level_rank=7, trump_suit=Suit.HEARTS)


def test_level_bid_round_trip_exists_for_some_deal() -> None:
    for seed in range(200):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=0, match_level_rank=10)
        opener = rh.declare_to_act_seat
        suit_opts = [o for o in rh.legal_declare_options(opener) if o["kind"] == "bid_suit"]
        if not suit_opts:
            continue
        s0 = suit_opts[0]["suit"]
        rh.declare_submit(opener, {"action": "bid_suit", "suit": s0})
        _autopass_until_play(rh)
        assert rh.phase == "play"
        assert rh.trump.trump_suit is not None and rh.trump.trump_suit.value == s0
        return
    raise AssertionError("no seed in range produced a callable suit main")
