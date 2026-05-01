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
    for seed in range(5000):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=0, match_level_rank=5)
        opener = rh.declare_to_act_seat
        suit_opts = [o for o in rh.legal_declare_options(opener) if o["kind"] in ("bid_plain", "bid_suit")]
        if not suit_opts:
            continue
        s0 = suit_opts[0]["suit"]
        rh.declare_submit(opener, {"action": "bid_plain", "suit": s0})
        _autopass_until_play(rh)
        assert rh.phase == "play"
        assert rh.trump.trump_suit is not None and rh.trump.trump_suit.value == s0
        return
    raise AssertionError("no seed in range produced a callable suit main")


def test_all_pass_keeps_bank_leader_is_right_of_bank() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=3, declarer_seat=2, match_level_rank=5)
    bank = rh.opening_bank_seat
    _autopass_until_play(rh)
    assert rh.declarer_seat == bank
    assert rh.leader == (bank + 1) % 4


def test_bid_winner_becomes_declarer_and_opens() -> None:
    for seed in range(12000):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=2, match_level_rank=5)
        opener = rh.declare_to_act_seat
        plain = [o for o in rh.legal_declare_options(opener) if o.get("kind") == "bid_plain"]
        if not plain:
            continue
        s0 = plain[0]["suit"]
        rh.declare_submit(opener, {"action": "bid_plain", "suit": s0})
        _autopass_until_play(rh)
        assert rh.declarer_seat == opener
        assert rh.leader == opener
        return
    raise AssertionError("no seed produced bid_plain for opener")


def test_declare_stakes_added_to_defender_final() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=100, declarer_seat=0, match_level_rank=5)
    opener = rh.declare_to_act_seat
    opts = rh.legal_declare_options(opener)
    bids = [o for o in opts if o["kind"] == "bid_plain"]
    assert bids
    rh.declare_submit(opener, {"action": "bid_plain", "suit": bids[0]["suit"]})
    assert rh.declare_stakes > 0
    _autopass_until_play(rh)
    while rh.phase != "scored":
        s = rh._to_act()
        o = rh.legal_combo_plays(s)
        assert o
        rh.play_cards(s, [c.cid for c in o[0]])
    assert rh.result is not None
    assert rh.result.declare_stakes_bonus == rh.declare_stakes
    assert rh.result.defender_points_final >= rh.result.declare_stakes_bonus
