"""Play (card-by-card) state machine.

After the auction ends with a contract:

- The opening lead comes from declarer's *left-hand opponent*.
- After the opening lead is on the table, dummy = declarer's partner. Dummy's
  hand becomes visible to everyone, and declarer plays both seats.
- Each subsequent trick: must follow suit if possible, otherwise any card.
- Trick winner = highest trump played, else highest card of the suit led.
- Winner of a trick leads the next trick.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .auction import Contract, Strain
from .cards import Card, Suit
from .seats import Seat, lho, next_seat, partner


def _strain_to_suit(s: Strain) -> Suit | None:
    if s == Strain.NOTRUMP:
        return None
    return Suit(s.value)


@dataclass
class Trick:
    leader: Seat
    cards: list[tuple[Seat, Card]] = field(default_factory=list)

    @property
    def led_suit(self) -> Suit | None:
        return self.cards[0][1].suit if self.cards else None

    @property
    def complete(self) -> bool:
        return len(self.cards) == 4

    def winner(self, trump: Suit | None) -> Seat:
        if not self.complete:
            raise ValueError("trick not complete")
        led = self.led_suit
        best_seat, best_card = self.cards[0]
        for seat, card in self.cards[1:]:
            if trump is not None and card.suit == trump and best_card.suit != trump:
                best_seat, best_card = seat, card
            elif trump is not None and card.suit == trump and best_card.suit == trump:
                if card.rank > best_card.rank:
                    best_seat, best_card = seat, card
            elif card.suit == led and best_card.suit == led:
                if card.rank > best_card.rank:
                    best_seat, best_card = seat, card
        return best_seat

    def to_dict(self) -> dict:
        return {
            "leader": self.leader.value,
            "cards": [{"seat": s.value, "card": c.to_dict()} for s, c in self.cards],
        }


@dataclass
class Play:
    contract: Contract
    hands: dict[Seat, list[Card]]
    tricks_played: list[Trick] = field(default_factory=list)
    current_trick: Trick | None = None
    declarer_tricks: int = 0
    defender_tricks: int = 0
    dummy_revealed: bool = False

    def __post_init__(self) -> None:
        if self.current_trick is None:
            self.current_trick = Trick(leader=lho(self.contract.declarer))

    @property
    def trump(self) -> Suit | None:
        return _strain_to_suit(self.contract.strain)

    @property
    def dummy(self) -> Seat:
        return partner(self.contract.declarer)

    @property
    def to_act(self) -> Seat:
        t = self.current_trick
        assert t is not None
        if not t.cards:
            return t.leader
        return next_seat(t.cards[-1][0])

    @property
    def acting_controller(self) -> Seat:
        """Seat that *decides* the next play.

        For dummy, that's the declarer (declarer plays both hands).
        """
        s = self.to_act
        if s == self.dummy and self.dummy_revealed:
            return self.contract.declarer
        return s

    def is_complete(self) -> bool:
        return len(self.tricks_played) == 13

    def legal_plays(self, seat: Seat) -> list[Card]:
        if seat != self.to_act:
            return []
        hand = self.hands[seat]
        t = self.current_trick
        assert t is not None
        if not t.cards:
            return list(hand)
        led = t.led_suit
        same = [c for c in hand if c.suit == led]
        return same if same else list(hand)

    def play_card(self, seat: Seat, card: Card) -> dict:
        """Play `card` from `seat`'s hand. Returns a dict describing what happened."""
        if seat != self.to_act:
            raise ValueError(f"not {seat}'s turn (waiting on {self.to_act})")
        if card not in self.hands[seat]:
            raise ValueError(f"{seat} does not hold {card.label}")
        if card not in self.legal_plays(seat):
            raise ValueError(f"illegal play: must follow suit ({card.label})")

        self.hands[seat].remove(card)
        t = self.current_trick
        assert t is not None
        t.cards.append((seat, card))

        events: list[dict] = [{"type": "card", "seat": seat.value, "card": card.to_dict()}]

        # Reveal dummy after the very first card (the opening lead)
        if (
            not self.dummy_revealed
            and len(self.tricks_played) == 0
            and len(t.cards) == 1
        ):
            self.dummy_revealed = True
            events.append({"type": "dummy_revealed", "seat": self.dummy.value})

        if t.complete:
            winner = t.winner(self.trump)
            self.tricks_played.append(t)
            if winner == self.contract.declarer or winner == self.dummy:
                self.declarer_tricks += 1
            else:
                self.defender_tricks += 1
            events.append({
                "type": "trick_won",
                "winner": winner.value,
                "trick_index": len(self.tricks_played) - 1,
            })
            if not self.is_complete():
                self.current_trick = Trick(leader=winner)
                events.append({"type": "lead", "seat": winner.value})
            else:
                self.current_trick = None
                events.append({"type": "play_complete"})

        return {"events": events}
