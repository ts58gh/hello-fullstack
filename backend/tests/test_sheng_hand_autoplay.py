"""Autoplay :class:`~app.sheng.hand.RunningHand` to completion (single-card rules)."""

from app.sheng.hand import RunningHand


def test_running_hand_autoplay_four_players_to_scored() -> None:
    rh = RunningHand.deal_new(num_players=4, seed=12345, declarer_seat=0, match_level_rank=9)
    safety = 0
    max_plays = 300
    while rh.phase != "scored":
        if rh.phase == "declare":
            rh.declare_submit(rh.declare_to_act_seat, {"action": "pass"})
            safety += 1
            continue
        seat = rh._to_act()
        opts = rh.legal_combo_plays(seat)
        assert opts, "no legal moves while hand not scored"
        rh.play_cards(seat, [c.cid for c in opts[0]])
        safety += 1
        assert safety < max_plays
    assert rh.result is not None
    assert rh.result.defender_points_final >= rh.result.defender_points_tricks_only
