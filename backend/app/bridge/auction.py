"""Auction (bidding) state machine.

Rules implemented:

- A *bid* is (level 1..7, strain in C/D/H/S/NT). It must outrank the previous bid:
  higher level, or same level and a strain higher in the strain order.
- *Pass* is always legal.
- *Double* is legal only if the last non-pass call was an opposing bid that is
  not currently doubled or redoubled.
- *Redouble* is legal only if the last non-pass call was your side's bid that
  is currently doubled.
- The auction ends:
    * with 4 passes from the start (no bids made)  -> "passed out", no contract
    * with 3 passes after any bid                  -> contract = (level, strain)
      with the doubled / redoubled status of that bid.
- Declarer = the first player on the contract-side to *name* the contract's
  strain in the auction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .seats import PARTNERSHIPS, SEAT_ORDER, Seat, next_seat


class Strain(str, Enum):
    CLUBS = "C"
    DIAMONDS = "D"
    HEARTS = "H"
    SPADES = "S"
    NOTRUMP = "NT"


STRAIN_ORDER = [Strain.CLUBS, Strain.DIAMONDS, Strain.HEARTS, Strain.SPADES, Strain.NOTRUMP]


@dataclass(frozen=True)
class Call:
    """A single auction call."""

    seat: Seat
    kind: str  # "bid" | "pass" | "double" | "redouble"
    level: int | None = None
    strain: Strain | None = None

    def to_dict(self) -> dict:
        d: dict = {"seat": self.seat.value, "kind": self.kind}
        if self.level is not None:
            d["level"] = self.level
        if self.strain is not None:
            d["strain"] = self.strain.value
        return d


def _bid_rank(level: int, strain: Strain) -> int:
    return level * 5 + STRAIN_ORDER.index(strain)


@dataclass
class Auction:
    dealer: Seat
    calls: list[Call] = field(default_factory=list)

    @property
    def to_act(self) -> Seat:
        if not self.calls:
            return self.dealer
        return next_seat(self.calls[-1].seat)

    def _last_bid(self) -> Call | None:
        for c in reversed(self.calls):
            if c.kind == "bid":
                return c
        return None

    def _doubled_state(self) -> str:
        """One of "" / "X" / "XX" -- status applied to the last bid."""
        for c in reversed(self.calls):
            if c.kind == "bid":
                return ""
            if c.kind == "double":
                return "X"
            if c.kind == "redouble":
                return "XX"
        return ""

    def is_complete(self) -> bool:
        if len(self.calls) < 4:
            return False
        if all(c.kind == "pass" for c in self.calls[-4:]) and len(self.calls) == 4 and not self._last_bid():
            # 4 passes from the start -> passed out
            return True
        if self._last_bid() and len(self.calls) >= 3 and all(c.kind == "pass" for c in self.calls[-3:]):
            return True
        return False

    # ---- legal-call enumeration -----------------------------------------

    def legal_calls(self) -> list[Call]:
        if self.is_complete():
            return []
        seat = self.to_act
        out: list[Call] = [Call(seat, "pass")]

        last = self._last_bid()
        last_rank = _bid_rank(last.level, last.strain) if last else 0  # type: ignore[arg-type]
        for level in range(1, 8):
            for strain in STRAIN_ORDER:
                if _bid_rank(level, strain) > last_rank:
                    out.append(Call(seat, "bid", level=level, strain=strain))

        if last is not None:
            doubled = self._doubled_state()
            opp = PARTNERSHIPS[last.seat] != PARTNERSHIPS[seat]
            if opp and doubled == "":
                out.append(Call(seat, "double"))
            if (not opp) and doubled == "X":
                out.append(Call(seat, "redouble"))
        return out

    # ---- mutators -------------------------------------------------------

    def call(self, kind: str, level: int | None = None, strain: Strain | None = None) -> Call:
        seat = self.to_act
        if self.is_complete():
            raise ValueError("auction is over")
        if kind == "bid":
            if level is None or strain is None:
                raise ValueError("bid requires level + strain")
            new = Call(seat, "bid", level=level, strain=strain)
        elif kind in ("pass", "double", "redouble"):
            new = Call(seat, kind)
        else:
            raise ValueError(f"unknown call kind {kind!r}")

        if not any(_calls_equal(new, c) for c in self.legal_calls()):
            raise ValueError(f"illegal call: {new}")

        self.calls.append(new)
        return new


def _calls_equal(a: Call, b: Call) -> bool:
    return a.kind == b.kind and a.level == b.level and a.strain == b.strain


# ---------------------------------------------------------------------------
# Contract derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contract:
    level: int
    strain: Strain
    declarer: Seat
    doubled: str  # "" | "X" | "XX"

    def tricks_required(self) -> int:
        """Tricks declarer side needs to *make* (book + level)."""
        return 6 + self.level

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "strain": self.strain.value,
            "declarer": self.declarer.value,
            "doubled": self.doubled,
            "tricks_required": self.tricks_required(),
        }


def derive_contract(auction: Auction) -> Contract | None:
    """If the auction is complete with a winning bid, return the contract.

    Returns None if the auction was passed out.
    """
    if not auction.is_complete():
        return None
    last = auction._last_bid()
    if last is None:
        return None  # passed out

    side = PARTNERSHIPS[last.seat]
    declarer: Seat | None = None
    for c in auction.calls:
        if c.kind == "bid" and c.strain == last.strain and PARTNERSHIPS[c.seat] == side:
            declarer = c.seat
            break
    assert declarer is not None  # last itself satisfies the predicate

    doubled = auction._doubled_state()
    return Contract(
        level=last.level,  # type: ignore[arg-type]
        strain=last.strain,  # type: ignore[arg-type]
        declarer=declarer,
        doubled=doubled,
    )


def calls_to_dicts(auction: Auction) -> list[dict]:
    return [c.to_dict() for c in auction.calls]


# Re-export for convenience -- some callers prefer enumerating seats from here.
__all__ = [
    "Auction",
    "Call",
    "Contract",
    "Strain",
    "STRAIN_ORDER",
    "calls_to_dicts",
    "derive_contract",
    "SEAT_ORDER",
]
