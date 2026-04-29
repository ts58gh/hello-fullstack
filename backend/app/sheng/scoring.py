"""Point cards and level-delta ladders for classic 升级 (phase-1)."""

from __future__ import annotations

import math

from .cards import JokerFace, PhysCard


def point_value(c: PhysCard) -> int:
    """Classic 计分 cards: ``5``, ``10``, ``K``."""

    if isinstance(c.face, JokerFace):
        return 0
    rk = c.face.rank
    if rk == 5:
        return 5
    if rk == 10:
        return 10
    if rk == 13:  # K
        return 10
    return 0


def points_in_cards(cards: list[PhysCard]) -> int:
    return sum(point_value(c) for c in cards)


def defenders_threshold(player_count: int) -> int:
    if player_count == 4:
        return 80
    if player_count == 6:
        return 120
    raise ValueError("unsupported player_count")


def level_change_after_deal(defender_points: int, threshold: int) -> dict:
    """Return level deltas for BOTH teams on the declaring hand.

    * When ``defender_points`` is strictly below ``threshold``: the declarer-side
      (庄家) earns levels while defenders stay unchanged.
    * When ``defender_points`` **equals** ``threshold``: **平局 (方案 B)** —
      defenders take the dealer seat next **without levelling**.
    * When ``defender_points`` exceeds ``threshold``: defenders steal levels;
      declarers stay flat (see classic tables).
    """

    if defender_points == threshold:
        return {
            "tie_at_threshold": True,
            "dealer_side_delta": 0,
            "defenders_side_delta": 0,
            "swap_without_level": True,
        }

    if defender_points < threshold:
        dealer_side_delta = _dealer_win_delta(defender_points, threshold)
        return {
            "tie_at_threshold": False,
            "dealer_side_delta": dealer_side_delta,
            "defenders_side_delta": 0,
            "swap_without_level": False,
        }

    margin = defender_points - threshold  # attacker success margin
    defenders_gain = math.ceil(margin / 40)
    return {
        "tie_at_threshold": False,
        "dealer_side_delta": 0,
        "defenders_side_delta": defenders_gain,
        "swap_without_level": False,
    }


def _dealer_win_delta(def_pts: int, th: int) -> int:
    """Table from the spec (defender points **below** threshold)."""

    if def_pts < 0 or def_pts >= th:
        raise ValueError("def_pts out of range for dealer-win branch")
    if def_pts == 0:
        return 3
    if 1 <= def_pts <= th - 41:  # 1..39 when th=80
        return 3
    if th - 40 <= def_pts <= th - 1:  # 40..79 when th=80
        return 2
    raise RuntimeError("unreachable")  # pragma: no cover


def kitty_multiplier_for_last_trick(*, num_cards_in_leading_combo: int) -> int:
    """``底牌`` bonus line: ``2 × (# cards in leading combo)``."""

    width = max(1, num_cards_in_leading_combo)
    return 2 * width
