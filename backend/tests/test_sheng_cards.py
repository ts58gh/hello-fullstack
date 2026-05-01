from app.sheng.cards import build_shoe, deal, shoe_size_for_players


def test_shoe_sizes():
    shoe4 = build_shoe(shoe_size_for_players(4))
    assert len(shoe4) == 108
    shoe6 = build_shoe(shoe_size_for_players(6))
    assert len(shoe6) == 162


def test_deal_partition_four():
    shoe = build_shoe(2)
    hands, kitty, flat = deal(shoe, 4, seed=12345)
    assert len(hands) == 4
    assert all(len(h) == 25 for h in hands)
    assert len(kitty) == 8
    assert len(flat) == 100


def test_deal_partition_six():
    shoe = build_shoe(3)
    hands, kitty, flat = deal(shoe, 6, seed=42)
    assert len(hands) == 6 and all(len(h) == 25 for h in hands)
    assert len(kitty) == 12
    assert len(flat) == 150
