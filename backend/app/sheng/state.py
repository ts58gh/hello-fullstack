"""High-level state objects (skeleton for later integration with HTTP/WS)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .friend import FriendCall
from .trump import TrumpContext


class DealPhase(str, Enum):
    DECLARE = "declaration"  # bidding / 反主 during deal
    KITTY_N_FRIEND = "kitty_friend"  # take kitty, bury, name friends (6p)
    PLAY = "play"
    HAND_OVER = "hand_over"


TeamId = Literal["A", "B"]


@dataclass
class TeamTableau:
    """Per-partnership ladder level (2..A encoded as int rank 2..14)."""

    level_rank: int = 2


@dataclass
class ShengMatch:
    teams: dict[TeamId, TeamTableau] = field(
        default_factory=lambda: {"A": TeamTableau(), "B": TeamTableau()}
    )


@dataclass
class ShengDeal:
    """Minimal deal bag — engine core will grow here in phase 2."""

    num_players: int
    phase: DealPhase = DealPhase.DECLARE
    trump: TrumpContext | None = None
    friend_calls: tuple[FriendCall, ...] = ()
