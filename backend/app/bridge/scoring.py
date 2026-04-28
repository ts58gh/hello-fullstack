"""Simplified non-vulnerable contract scoring.

Implemented:
- Trick score (per contract trick of declared level): 20/minor, 30/major,
  30/30 NT (with NT first trick = 40 -- handled).
- Doubled contracts: trick score x2; redoubled: x4.
- Game bonus 300 / part-score bonus 50 (non-vul).
- Slam bonuses: small slam 500, grand slam 1000 (non-vul).
- Doubled overtrick bonus: 100 each (non-vul); redoubled: 200 each.
- Insult bonus: +50 for making a doubled contract; +100 for redoubled.
- Undertricks: 50 each (non-vul); doubled: 100, 200, 200, 300, ...; redoubled: x2.

Skipped (intentional v1 simplification):
- Vulnerability
- Honors
- Penalty bonus differences for "first" undertrick distinctions on partials

Returns a positive number from declarer-side perspective; defenders get the
negation. The frontend can split it across the score sheet however it wants.
"""

from __future__ import annotations

from .auction import Contract, Strain


_PER_TRICK = {
    Strain.CLUBS: 20,
    Strain.DIAMONDS: 20,
    Strain.HEARTS: 30,
    Strain.SPADES: 30,
    Strain.NOTRUMP: 30,  # plus a +10 bump for the first NT trick
}


def _doubling_multiplier(doubled: str) -> int:
    return {"": 1, "X": 2, "XX": 4}[doubled]


def score_contract(contract: Contract, declarer_tricks: int) -> dict:
    needed = contract.tricks_required()
    over = declarer_tricks - needed
    mult = _doubling_multiplier(contract.doubled)

    detail: dict = {
        "made": over >= 0,
        "tricks": declarer_tricks,
        "needed": needed,
        "overtricks": max(0, over),
        "undertricks": max(0, -over),
        "trick_score": 0,
        "overtrick_bonus": 0,
        "game_or_part_bonus": 0,
        "slam_bonus": 0,
        "insult_bonus": 0,
        "undertrick_penalty": 0,
        "total": 0,
    }

    if over >= 0:
        per = _PER_TRICK[contract.strain]
        # First trick in NT is 40 instead of 30
        if contract.strain == Strain.NOTRUMP:
            trick_score = (per * contract.level + 10) * mult
        else:
            trick_score = per * contract.level * mult
        detail["trick_score"] = trick_score

        if contract.doubled == "":
            overtrick_bonus = per * over
        elif contract.doubled == "X":
            overtrick_bonus = 100 * over
        else:  # XX
            overtrick_bonus = 200 * over
        detail["overtrick_bonus"] = overtrick_bonus

        if trick_score >= 100:
            game_bonus = 300  # non-vul game
        else:
            game_bonus = 50  # part-score
        detail["game_or_part_bonus"] = game_bonus

        slam = 0
        if contract.level == 6:
            slam = 500
        elif contract.level == 7:
            slam = 1000
        detail["slam_bonus"] = slam

        insult = 0
        if contract.doubled == "X":
            insult = 50
        elif contract.doubled == "XX":
            insult = 100
        detail["insult_bonus"] = insult

        total = trick_score + overtrick_bonus + game_bonus + slam + insult
        detail["total"] = total
    else:
        n = -over  # number of undertricks
        if contract.doubled == "":
            penalty = 50 * n
        else:
            base_mult = 1 if contract.doubled == "X" else 2
            # Non-vul doubled: 100, 300, 500, 800, 1100, 1400, ...
            # i.e. 100 first, 200 next two, 300 each thereafter
            penalty = 0
            for k in range(1, n + 1):
                if k == 1:
                    penalty += 100
                elif k <= 3:
                    penalty += 200
                else:
                    penalty += 300
            penalty *= base_mult
        detail["undertrick_penalty"] = penalty
        detail["total"] = -penalty

    return detail
