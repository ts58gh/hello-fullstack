"""Simple bridge bots.

Both bots return *legal* actions only. Strategy is deliberately simple:

Bidding:
- Open with high-card-points + a chosen suit; respond conservatively.
- Pass aggressively when in doubt -- this keeps auctions short and contracts
  reasonable rather than wild.

Play:
- If you can legally win the trick cheaply, do.
- Otherwise dump the lowest legal card.
- On lead, lead the highest card from a long suit you also have a top card in,
  else lead a low card from your longest suit.

These are not strong bridge AIs, but they make legal, somewhat-sensible plays
so a human can have a coherent game.
"""

from __future__ import annotations

import random
from collections import defaultdict

from .auction import Auction, Call, Strain, STRAIN_ORDER
from .cards import Card, Suit, hcp
from .play import Play
from .seats import PARTNERSHIPS, Seat, partner
from .state import Deal, Phase


# ---------------------------------------------------------------------------
# Bidding bot
# ---------------------------------------------------------------------------


def _suit_lengths(hand: list[Card]) -> dict[Suit, int]:
    out: dict[Suit, int] = {s: 0 for s in (Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES)}
    for c in hand:
        out[c.suit] += 1
    return out


def _longest_suit(hand: list[Card]) -> Suit:
    lengths = _suit_lengths(hand)
    # Prefer majors on ties; among majors, spades; among minors, diamonds.
    pref = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]
    return max(pref, key=lambda s: (lengths[s], -pref.index(s)))


def _is_balanced(hand: list[Card]) -> bool:
    lengths = sorted(_suit_lengths(hand).values(), reverse=True)
    return lengths in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2])


def choose_call(deal: Deal, seat: Seat) -> Call:
    """Return one legal call for the bot at `seat`. Caller should `auction.call(...)` it."""
    auction = deal.auction
    hand = deal.hands[seat]
    legal = auction.legal_calls()
    points = hcp(hand)

    last_bid = auction._last_bid()
    last_bidder_side = PARTNERSHIPS[last_bid.seat] if last_bid else None
    my_side = PARTNERSHIPS[seat]

    # If our partner already declared a strain at level >= 2, just pass --
    # don't get fancy.
    partner_seat = partner(seat)
    partner_called_bid = any(c.kind == "bid" and c.seat == partner_seat for c in auction.calls)

    pass_call = next(c for c in legal if c.kind == "pass")

    # Opening (no prior bids):
    if last_bid is None:
        if points >= 15 and _is_balanced(hand):
            # 1NT
            cand = next((c for c in legal if c.kind == "bid" and c.level == 1 and c.strain == Strain.NOTRUMP), None)
            if cand:
                return cand
        if points >= 13:
            suit = _longest_suit(hand)
            strain = Strain(suit.value)
            cand = next((c for c in legal if c.kind == "bid" and c.level == 1 and c.strain == strain), None)
            if cand:
                return cand
        return pass_call

    # Responding to partner's opening bid (last bid was partner's, low level)
    if last_bidder_side == my_side and partner_called_bid and last_bid.level == 1:
        if points >= 6:
            # Raise partner's suit if we have 4+ of it; else bid our longest at 1- or 2-level.
            partner_strain = last_bid.strain
            if partner_strain != Strain.NOTRUMP:
                partner_suit = Suit(partner_strain.value)
                if _suit_lengths(hand)[partner_suit] >= 4:
                    cand = next(
                        (c for c in legal if c.kind == "bid" and c.level == 2 and c.strain == partner_strain),
                        None,
                    )
                    if cand and points <= 10:
                        return cand
            my_suit = _longest_suit(hand)
            my_strain = Strain(my_suit.value)
            for level in (1, 2):
                cand = next(
                    (c for c in legal if c.kind == "bid" and c.level == level and c.strain == my_strain),
                    None,
                )
                if cand:
                    return cand
        return pass_call

    # Overcalls (opponent opened):
    if last_bidder_side != my_side and last_bid.level == 1:
        if points >= 11:
            my_suit = _longest_suit(hand)
            if _suit_lengths(hand)[my_suit] >= 5:
                my_strain = Strain(my_suit.value)
                # cheapest level over their bid in our suit
                for level in (1, 2):
                    cand = next(
                        (c for c in legal if c.kind == "bid" and c.level == level and c.strain == my_strain),
                        None,
                    )
                    if cand:
                        return cand
        return pass_call

    # Anything more complex -> pass. Keeps auctions sane.
    return pass_call


# ---------------------------------------------------------------------------
# Play bot
# ---------------------------------------------------------------------------


def choose_play(deal: Deal, seat_to_play: Seat, controller: Seat) -> Card:
    """Return the card the bot at `controller` should play from `seat_to_play`.

    Note: when controller plays from dummy, controller != seat_to_play.
    """
    assert deal.phase == Phase.PLAY and deal.play is not None
    play: Play = deal.play
    hand = deal.hands[seat_to_play]
    legal = play.legal_plays(seat_to_play)
    if not legal:
        # Should never happen mid-trick; fall back gracefully.
        return random.choice(hand)

    trick = play.current_trick
    assert trick is not None
    trump = play.trump

    # Are we leading?
    if not trick.cards:
        return _lead(hand, trump, controller, play)

    # Following.
    led = trick.led_suit
    led_in_trick = [c for _, c in trick.cards]
    current_winner_seat, current_winner_card = max(
        trick.cards,
        key=lambda sc: _card_strength(sc[1], led, trump),
    )
    partner_winning = (
        PARTNERSHIPS.get(current_winner_seat) == PARTNERSHIPS[seat_to_play]
    )

    legal_in_led = [c for c in legal if c.suit == led]
    if legal_in_led:
        # Must follow suit.
        if partner_winning:
            # Don't waste a high card; throw the lowest in suit.
            return min(legal_in_led, key=lambda c: c.rank)
        # Try cheapest card that beats the current winner.
        beats = [c for c in legal_in_led if _card_strength(c, led, trump) > _card_strength(current_winner_card, led, trump)]
        if beats:
            return min(beats, key=lambda c: c.rank)
        return min(legal_in_led, key=lambda c: c.rank)

    # Can't follow suit.
    if partner_winning:
        return _discard_lowest(legal, trump)

    # Try a low trump if available and that wins.
    if trump is not None:
        trumps = [c for c in legal if c.suit == trump]
        if trumps:
            cur_strength = _card_strength(current_winner_card, led, trump)
            beats = [c for c in trumps if _card_strength(c, led, trump) > cur_strength]
            if beats:
                return min(beats, key=lambda c: c.rank)
    return _discard_lowest(legal, trump)


def _card_strength(card: Card, led: Suit | None, trump: Suit | None) -> int:
    """Higher = stronger inside a single trick."""
    if trump is not None and card.suit == trump:
        return 200 + card.rank
    if led is not None and card.suit == led:
        return 100 + card.rank
    return card.rank  # off-suit can't win


def _lead(hand: list[Card], trump: Suit | None, controller: Seat, play: Play) -> Card:
    by_suit: dict[Suit, list[Card]] = defaultdict(list)
    for c in hand:
        by_suit[c.suit].append(c)
    for s, cs in by_suit.items():
        cs.sort(key=lambda c: -c.rank)

    # Avoid leading trump on opening lead unless it's our only suit.
    candidates = [s for s in by_suit if by_suit[s]]
    if trump is not None:
        non_trump = [s for s in candidates if s != trump]
        if non_trump:
            candidates = non_trump

    # Lead from the longest candidate suit. Prefer 4th-best from longest:
    # it's a real bridge convention and works OK as a generic heuristic.
    candidates.sort(key=lambda s: (-len(by_suit[s]), s.value))
    chosen_suit = candidates[0]
    cs = by_suit[chosen_suit]
    if len(cs) >= 4:
        return cs[3]  # 4th-highest
    return cs[0]  # otherwise top of the suit


def _discard_lowest(legal: list[Card], trump: Suit | None) -> Card:
    non_trumps = [c for c in legal if trump is None or c.suit != trump]
    pool = non_trumps if non_trumps else legal
    return min(pool, key=lambda c: c.rank)
