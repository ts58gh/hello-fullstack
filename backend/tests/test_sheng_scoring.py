from app.sheng.scoring import defenders_threshold, level_change_after_deal


def test_thresholds():
    assert defenders_threshold(4) == 80
    assert defenders_threshold(6) == 120


def test_tie_at_threshold_swap_zero_delta():
    r = level_change_after_deal(80, 80)
    assert r["tie_at_threshold"] is True
    assert r["swap_without_level"] is True
    assert r["dealer_side_delta"] == 0
    assert r["defenders_side_delta"] == 0


def test_dealer_win_bands():
    assert level_change_after_deal(0, 80)["dealer_side_delta"] == 3
    assert level_change_after_deal(10, 80)["dealer_side_delta"] == 3
    assert level_change_after_deal(40, 80)["dealer_side_delta"] == 2
    assert level_change_after_deal(79, 80)["dealer_side_delta"] == 2


def test_defenders_over_threshold_linear():
    r = level_change_after_deal(120, 80)
    assert r["defenders_side_delta"] == 1  # margin 40 -> ceil(40/40)=1
    r2 = level_change_after_deal(200, 80)
    assert r2["defenders_side_delta"] == 3  # margin 120 -> ceil(120/40)=3
