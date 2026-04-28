"""Seats and partnerships."""

from __future__ import annotations

from enum import Enum


class Seat(str, Enum):
    NORTH = "N"
    EAST = "E"
    SOUTH = "S"
    WEST = "W"


SEAT_ORDER = [Seat.NORTH, Seat.EAST, Seat.SOUTH, Seat.WEST]


def next_seat(s: Seat) -> Seat:
    return SEAT_ORDER[(SEAT_ORDER.index(s) + 1) % 4]


def partner(s: Seat) -> Seat:
    return SEAT_ORDER[(SEAT_ORDER.index(s) + 2) % 4]


def lho(s: Seat) -> Seat:
    """Left-hand opponent (the seat that bids/leads after `s`)."""
    return next_seat(s)


def rho(s: Seat) -> Seat:
    """Right-hand opponent."""
    return SEAT_ORDER[(SEAT_ORDER.index(s) - 1) % 4]


PARTNERSHIPS: dict[Seat, str] = {
    Seat.NORTH: "NS",
    Seat.SOUTH: "NS",
    Seat.EAST: "EW",
    Seat.WEST: "EW",
}


def same_side(a: Seat, b: Seat) -> bool:
    return PARTNERSHIPS[a] == PARTNERSHIPS[b]
