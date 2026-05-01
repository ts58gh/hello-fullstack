"""叫主 MVP: pass chain ends deal; suit / 无主 bids require material in hand (visible during deal)."""

import pytest

from app.sheng.cards import Suit
from app.sheng.hand import RunningHand
from app.sheng.trump import TrumpContext


def _bury_min_ids(rh: RunningHand) -> None:
    assert rh.phase == "kitty"
    d = rh.declarer_seat
    bury = sorted([c.cid for c in rh.hands[d]])[: rh.bury_card_count]
    rh.bury_submit(d, bury)


def _declare_passes_to_kitty(rh: RunningHand) -> None:
    while rh.phase == "declare":
        moved = False
        for s in range(rh.num_players):
            if rh.legal_declare_options(s):
                rh.declare_submit(s, {"action": "pass"})
                moved = True
                break
        assert moved


def test_cannot_overbid_own_call_when_turn_returns() -> None:
    """亮满后按序叫主时，最高叫品者轮转回来只能「过」，不能再抬自己的主。"""

    for seed in range(300):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=0, match_level_rank=7)
        rh.reveal_full_deal()
        a = rh.declare_to_act_seat
        opts = [o for o in rh.legal_declare_options(a) if o.get("kind") == "bid_plain"]
        if not opts:
            continue
        suit = opts[0]["suit"]
        rh.declare_submit(a, {"action": "bid_plain", "suit": suit})
        for _ in range(3):
            rh.declare_submit(rh.declare_to_act_seat, {"action": "pass"})
        assert rh.declare_to_act_seat == a
        assert rh.legal_declare_options(a) == [{"kind": "pass"}]
        with pytest.raises(PermissionError):
            rh.declare_submit(a, {"action": "bid_plain", "suit": suit})
        return
    pytest.fail("no seed produced bid_plain from first actor in 300 tries")


def _declare_then_bury_auto(rh: RunningHand) -> None:
    _declare_passes_to_kitty(rh)
    _bury_min_ids(rh)


def test_declare_showcase_tracks_current_bid_and_clears_on_finish() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=55, declarer_seat=0, match_level_rank=7)
    rh.reveal_full_deal()
    a = rh.declare_to_act_seat
    opts = [o for o in rh.legal_declare_options(a) if o.get("kind") == "bid_plain"]
    assert opts
    suit = opts[0]["suit"]
    rh.declare_submit(a, {"action": "bid_plain", "suit": suit})
    assert rh._declare_face_up_seat == a and len(rh._declare_face_up) == 1
    hid_cid = rh._declare_face_up[0].cid
    assert all(c.cid != hid_cid for c in rh._pile_for_declare_checks(a))
    _declare_passes_to_kitty(rh)
    assert rh.phase == "kitty"
    assert rh._declare_face_up_seat is None and len(rh._declare_face_up) == 0


def test_all_pass_defaults_hearts_then_play_phase() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=999, declarer_seat=0, match_level_rank=7)
    rh.reveal_full_deal()
    assert rh.phase == "declare"
    _declare_then_bury_auto(rh)
    assert rh.phase == "play"
    assert rh.trump == TrumpContext(level_rank=7, trump_suit=Suit.HEARTS)


def test_level_bid_round_trip_exists_for_some_deal() -> None:
    for seed in range(5000):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=0, match_level_rank=5)
        rh.reveal_full_deal()
        opener = rh.declare_to_act_seat
        suit_opts = [o for o in rh.legal_declare_options(opener) if o["kind"] in ("bid_plain", "bid_suit")]
        if not suit_opts:
            continue
        s0 = suit_opts[0]["suit"]
        rh.declare_submit(opener, {"action": "bid_plain", "suit": s0})
        _declare_passes_to_kitty(rh)
        _bury_min_ids(rh)
        assert rh.phase == "play"
        assert rh.trump.trump_suit is not None and rh.trump.trump_suit.value == s0
        return
    raise AssertionError("no seed in range produced a callable suit main")


def test_all_pass_keeps_bank_leader_is_right_of_bank() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=3, declarer_seat=2, match_level_rank=5)
    rh.reveal_full_deal()
    bank = rh.opening_bank_seat
    _declare_then_bury_auto(rh)
    assert rh.declarer_seat == bank
    assert rh.leader == (bank + 1) % 4


def test_bid_winner_becomes_declarer_and_opens() -> None:
    for seed in range(12000):
        rh = RunningHand.deal_new(num_players=4, seed=seed, declarer_seat=2, match_level_rank=5)
        rh.reveal_full_deal()
        opener = rh.declare_to_act_seat
        plain = [o for o in rh.legal_declare_options(opener) if o.get("kind") == "bid_plain"]
        if not plain:
            continue
        s0 = plain[0]["suit"]
        rh.declare_submit(opener, {"action": "bid_plain", "suit": s0})
        _declare_passes_to_kitty(rh)
        _bury_min_ids(rh)
        assert rh.declarer_seat == opener
        assert rh.leader == opener
        return
    raise AssertionError("no seed produced bid_plain for opener")


def test_declare_stakes_added_to_defender_final() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=100, declarer_seat=0, match_level_rank=5)
    rh.reveal_full_deal()
    opener = rh.declare_to_act_seat
    opts = rh.legal_declare_options(opener)
    bids = [o for o in opts if o["kind"] == "bid_plain"]
    assert bids
    rh.declare_submit(opener, {"action": "bid_plain", "suit": bids[0]["suit"]})
    assert rh.declare_stakes > 0
    _declare_passes_to_kitty(rh)
    _bury_min_ids(rh)
    while rh.phase != "scored":
        s = rh._to_act()
        o = rh.legal_combo_plays(s)
        assert o
        rh.play_cards(s, [c.cid for c in o[0]])
    assert rh.result is not None
    assert rh.result.declare_stakes_bonus == rh.declare_stakes
    assert rh.result.defender_points_final >= rh.result.declare_stakes_bonus


def test_progressive_visibility_is_subset_of_full_hand() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=101, declarer_seat=0, match_level_rank=9)
    rh.deal_reveal_steps = 7
    for s in range(4):
        vis = {c.cid for c in rh._visible_cards(s)}
        full = {c.cid for c in rh.hands[s]}
        assert vis <= full


def test_bury_hand_count_and_kitty_restored() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=42, declarer_seat=1, match_level_rank=3)
    rh.reveal_full_deal()
    _declare_then_bury_auto(rh)
    assert len(rh.kitty) == 8
    for h in rh.hands:
        assert len(h) == 25
