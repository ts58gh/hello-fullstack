"""朋友牌 tracking (`第 N 张` semantics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cards import JokerFace, PhysCard, RegularFace, Suit


@dataclass(frozen=True)
class FriendCall:
    """``nth`` is 1-based — the *global* play order of that natural card identity."""

    nth: int
    suit: Suit
    rank: int

    def __post_init__(self) -> None:
        if self.nth < 1:
            raise ValueError("nth must be positive")


def parse_friend_calls(rows: list[dict[str, Any]] | None) -> tuple[FriendCall, ...]:
    """Build engine ``FriendCall`` tuples from JSON-like dicts (``suit`` = ``C|D|H|S``)."""

    if not rows:
        return ()
    out: list[FriendCall] = []
    for row in rows:
        out.append(
            FriendCall(
                nth=int(row["nth"]),
                suit=Suit(str(row["suit"])),
                rank=int(row["rank"]),
            )
        )
    return tuple(out)


@dataclass
class FriendRevealEvent:
    call: FriendCall
    reveal_seat: int


class FriendPlayTracker:
    """Tracks how many times each ``(rank, suit)`` has been played."""

    def __init__(self, calls: tuple[FriendCall, ...]) -> None:
        self._active = {fc for fc in calls}
        self._revealed: dict[FriendCall, int] = {}
        self._seen: dict[tuple[str, int], int] = {}

    def observe(self, seat_idx: int, card: PhysCard) -> list[FriendRevealEvent]:
        f = card.face
        if isinstance(f, JokerFace):
            return []

        assert isinstance(f, RegularFace)
        key = (f.suit.value, f.rank)

        times = self._seen.get(key, 0) + 1
        self._seen[key] = times

        outs: list[FriendRevealEvent] = []
        for fc in tuple(self._active):
            if fc.suit != f.suit or fc.rank != f.rank:
                continue
            if times < fc.nth:
                continue

            if fc in self._revealed:
                continue

            self._revealed[fc] = seat_idx
            self._active.remove(fc)
            outs.append(FriendRevealEvent(call=fc, reveal_seat=seat_idx))

        return outs
