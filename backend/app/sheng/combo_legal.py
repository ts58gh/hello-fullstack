"""Legal multi-card leads and follows (pairs / triples / plain-suit tractors).

Shapes match :mod:`combos`; follow prioritises leading plain suit / trump similarly
to single-card logic in :mod:`follow`.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations, product

from .cards import JokerFace, PhysCard, RegularFace, Suit
from .combos import ComboKind, ParsedCombo, parse_combo
from .combos import _legal_pair as legal_pair_cards
from .combos import _legal_triple as legal_triple_cards
from .follow import follow_candidates_single
from .trump import TrumpContext, is_trump, strength_key


def _is_plain_in_suit(ctx: TrumpContext, c: PhysCard, suit: Suit) -> bool:
    f = c.face
    if isinstance(f, JokerFace):
        return False
    assert isinstance(f, RegularFace)
    if f.suit != suit:
        return False
    return not is_trump(ctx, c)


_TRACT_PROD_CAP = 400


def _hand_pairs_unique(ctx: TrumpContext, hand: list[PhysCard]) -> list[tuple[PhysCard, PhysCard]]:
    hs = sorted(hand, key=lambda c: c.cid)
    pairs: list[tuple[PhysCard, PhysCard]] = []
    seen: set[tuple[int, int]] = set()
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            if not legal_pair_cards(ctx, hs[i], hs[j]):
                continue
            a, b = hs[i].cid, hs[j].cid
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((hs[i], hs[j]))
    return pairs


def _plain_rank_bins(ctx: TrumpContext, suit: Suit, hand: list[PhysCard]) -> dict[int, list[PhysCard]]:
    by: dict[int, list[PhysCard]] = defaultdict(list)
    for c in hand:
        if _is_plain_in_suit(ctx, c, suit):
            f = c.face
            assert isinstance(f, RegularFace)
            by[f.rank].append(c)
    return dict(by)


def _enumerate_plain_tractors_fixed(
    ctx: TrumpContext,
    ranks_sorted: tuple[int, ...],
    rank_to_cards: dict[int, tuple[PhysCard, ...]],
) -> list[list[PhysCard]]:
    pair_lists: list[list[tuple[PhysCard, PhysCard]]] = []
    for r in ranks_sorted:
        combos = [(a, b) for a, b in combinations(rank_to_cards[r], 2) if legal_pair_cards(ctx, a, b)]
        pair_lists.append(combos)
    if any(len(xs) == 0 for xs in pair_lists):
        return []
    prods = list(product(*pair_lists))
    if len(prods) > _TRACT_PROD_CAP:
        return []
    out: list[list[PhysCard]] = []
    for choice in prods:
        cards: list[PhysCard] = []
        for a, b in choice:
            cards.extend([a, b])
        try:
            parse_combo(ctx, cards)
        except ValueError:
            continue
        out.append(sorted(cards, key=lambda c: c.cid))
    return out


def enumerate_plain_tractors_in_hand(ctx: TrumpContext, hand: list[PhysCard]) -> list[list[PhysCard]]:
    """All legal plain-suit tractors drawable from ``hand``."""
    seen: set[frozenset[int]] = set()
    out: list[list[PhysCard]] = []
    for suit in Suit:
        by_r = _plain_rank_bins(ctx, suit, hand)
        if not by_r:
            continue
        ranks_eff = tuple(r for r in sorted(by_r) if len(by_r[r]) >= 2)
        if len(ranks_eff) < 2:
            continue
        i_seg = 0
        while i_seg < len(ranks_eff):
            j_seg = i_seg
            while j_seg + 1 < len(ranks_eff) and ranks_eff[j_seg + 1] == ranks_eff[j_seg] + 1:
                j_seg += 1
            seg = ranks_eff[i_seg : j_seg + 1]
            i_seg = j_seg + 1
            if len(seg) < 2:
                continue
            rmap_trim = {r: tuple(by_r[r]) for r in seg}
            for wl in range(2, len(seg) + 1):
                for r0_i in range(0, len(seg) - wl + 1):
                    sub = tuple(seg[r0_i : r0_i + wl])
                    for cards in _enumerate_plain_tractors_fixed(ctx, sub, rmap_trim):
                        ks = frozenset(c.cid for c in cards)
                        if ks not in seen:
                            seen.add(ks)
                            out.append(cards)
    return out


def enumerate_hand_triples(ctx: TrumpContext, hand: list[PhysCard]) -> list[list[PhysCard]]:
    hs = sorted(hand, key=lambda c: c.cid)
    out: list[list[PhysCard]] = []
    seen: set[frozenset[int]] = set()
    for tri in combinations(hs, 3):
        if not legal_triple_cards(ctx, tri):
            continue
        k = frozenset(c.cid for c in tri)
        if k in seen:
            continue
        seen.add(k)
        out.append(sorted(tri, key=lambda c: c.cid))
    return out


def legal_leading_plays(ctx: TrumpContext, hand: list[PhysCard]) -> list[list[PhysCard]]:
    picks: dict[frozenset[int], list[PhysCard]] = {}

    def add(cards: list[PhysCard]) -> None:
        try:
            parse_combo(ctx, list(cards))
        except ValueError:
            return
        k = frozenset(c.cid for c in cards)
        if k not in picks:
            picks[k] = sorted(cards, key=lambda c: c.cid)

    for c in sorted(hand, key=lambda x: x.cid):
        add([c])
    for xa, xb in _hand_pairs_unique(ctx, hand):
        add([xa, xb])
    for t in enumerate_hand_triples(ctx, hand):
        add(t)
    for tr in enumerate_plain_tractors_in_hand(ctx, hand):
        add(tr)
    return sorted(picks.values(), key=lambda xs: (len(xs), tuple(c.cid for c in xs)))


def _distinct_k_pairs(pairings: list[tuple[PhysCard, PhysCard]], k: int) -> list[list[PhysCard]]:
    if k == 0 or len(pairings) < k:
        return []
    out: list[list[PhysCard]] = []
    seen: set[frozenset[int]] = set()
    for comb in combinations(pairings, k):
        ck: set[int] = set()
        ok = True
        cards: list[PhysCard] = []
        for a, b in comb:
            if a.cid in ck or b.cid in ck:
                ok = False
                break
            ck.add(a.cid)
            ck.add(b.cid)
            cards.extend([a, b])
        if not ok:
            continue
        ks = frozenset(ck)
        if ks in seen:
            continue
        seen.add(ks)
        out.append(sorted(cards, key=lambda c: c.cid))
        if len(out) >= _TRACT_PROD_CAP:
            break
    return out


def _tractor_ranks(led: ParsedCombo) -> tuple[int, ...]:
    by_rank: dict[int, int] = defaultdict(int)
    for c in led.cards:
        f = c.face
        assert isinstance(f, RegularFace)
        by_rank[f.rank] += 1
    ranks = sorted(by_rank.keys())
    for r in ranks:
        if by_rank[r] != 2:
            raise ValueError("bad tractor")
    if len(ranks) < 2:
        raise ValueError("bad tractor span")
    for a, b in zip(ranks, ranks[1:]):
        if b != a + 1:
            raise ValueError("bad tractor consecutive")
    return tuple(ranks)


def _tractor_plain_suit(led: ParsedCombo) -> Suit:
    f = led.cards[0].face
    assert isinstance(f, RegularFace)
    return f.suit


def legal_follow_plain_tractor(ctx: TrumpContext, led: ParsedCombo, hand: list[PhysCard]) -> list[list[PhysCard]]:
    suit = _tractor_plain_suit(led)
    ranks = _tractor_ranks(led)
    k = len(ranks)
    by_r = _plain_rank_bins(ctx, suit, hand)
    rmap = {r: tuple(by_r.get(r, ())) for r in ranks}

    perfection: list[list[PhysCard]] = []
    if all(len(rmap[r]) >= 2 for r in ranks):
        perfection = _enumerate_plain_tractors_fixed(ctx, ranks, {rr: tuple(by_r[rr]) for rr in ranks})

    if perfection:
        return perfection

    suit_pairs_s = [(a, b) for (a, b) in _hand_pairs_unique(ctx, hand) if _is_plain_in_suit(ctx, a, suit) and _is_plain_in_suit(ctx, b, suit)]
    broken = _distinct_k_pairs(suit_pairs_s, k)
    if broken:
        return broken

    trump_pairs_u = [(a, b) for (a, b) in _hand_pairs_unique(ctx, hand) if is_trump(ctx, a) and is_trump(ctx, b)]
    tbr = _distinct_k_pairs(trump_pairs_u, k)
    if tbr:
        return tbr

    allp = [(a, b) for (a, b) in _hand_pairs_unique(ctx, hand)]
    return _distinct_k_pairs(allp, k)


def legal_follow_pair(ctx: TrumpContext, led: ParsedCombo, hand: list[PhysCard]) -> list[list[PhysCard]]:
    a, b = led.cards

    plain_s_led: Suit | None = None
    fa, fb = a.face, b.face
    both_trump = is_trump(ctx, a) and is_trump(ctx, b)

    if (
        isinstance(fa, RegularFace)
        and isinstance(fb, RegularFace)
        and not both_trump
        and fa.suit == fb.suit
        and not is_trump(ctx, a)
        and not is_trump(ctx, b)
    ):
        plain_s_led = fa.suit

    uniq: dict[frozenset[int], list[PhysCard]] = {}

    def add_pair(xs: tuple[PhysCard, PhysCard]) -> None:
        x, y = xs
        if not legal_pair_cards(ctx, x, y):
            return
        k = frozenset({x.cid, y.cid})
        if k not in uniq:
            uniq[k] = sorted([x, y], key=lambda c: c.cid)

    for p in _hand_pairs_unique(ctx, hand):
        add_pair(p)

    if plain_s_led is not None:
        gs = plain_s_led
        good: dict[frozenset[int], list[PhysCard]] = {}
        for p in _hand_pairs_unique(ctx, hand):
            x, y = p
            if _is_plain_in_suit(ctx, x, gs) and _is_plain_in_suit(ctx, y, gs):
                k = frozenset({x.cid, y.cid})
                good[k] = sorted([x, y], key=lambda c: c.cid)
        if good:
            return sorted(good.values(), key=lambda zs: tuple(c.cid for c in zs))

    if both_trump:
        trump_only = {fk: fv for fk, fv in uniq.items() if all(is_trump(ctx, z) for z in fv)}
        if trump_only:
            return sorted(trump_only.values(), key=lambda zs: tuple(c.cid for c in zs))

    return sorted(uniq.values(), key=lambda zs: tuple(c.cid for c in zs))[:600]


def legal_follow_triple(ctx: TrumpContext, led: ParsedCombo, hand: list[PhysCard]) -> list[list[PhysCard]]:
    suits_led = {
        z.face.suit for z in led.cards if not is_trump(ctx, z) and isinstance(z.face, RegularFace)
    }
    all_t_map: dict[frozenset[int], list[PhysCard]] = {}

    def add(xs: list[PhysCard]) -> None:
        k = frozenset(z.cid for z in xs)
        if k not in all_t_map:
            all_t_map[k] = sorted(xs, key=lambda c: c.cid)

    for tri in enumerate_hand_triples(ctx, hand):
        add(tri)

    if led.cards and len(suits_led) == 1 and all(not is_trump(ctx, z) for z in led.cards):
        s_only = next(iter(suits_led))
        good = {
            fk: fv
            for fk, fv in all_t_map.items()
            if all(_is_plain_in_suit(ctx, z, s_only) for z in fv)
        }
        if good:
            return sorted(good.values(), key=lambda zs: tuple(c.cid for c in zs))

    if all(is_trump(ctx, z) for z in led.cards):
        mains = {fk: fv for fk, fv in all_t_map.items() if all(is_trump(ctx, z) for z in fv)}
        if mains:
            return sorted(mains.values(), key=lambda zs: tuple(c.cid for c in zs))

    return sorted(all_t_map.values(), key=lambda zs: tuple(c.cid for c in zs))[:600]


def legal_follow_combo(ctx: TrumpContext, led: ParsedCombo, hand: list[PhysCard]) -> list[list[PhysCard]]:
    if led.kind == ComboKind.SINGLE:
        return [[c] for c in follow_candidates_single(ctx, led.cards[0], hand)]
    if led.kind == ComboKind.PAIR:
        return legal_follow_pair(ctx, led, hand)
    if led.kind == ComboKind.TRIPLE:
        return legal_follow_triple(ctx, led, hand)
    if led.kind == ComboKind.TRACTOR_PAIR:
        return legal_follow_plain_tractor(ctx, led, hand)
    return []


def legal_plays_for_turn(ctx: TrumpContext, trick: list[tuple[int, tuple[PhysCard, ...]]], hand: list[PhysCard]) -> list[list[PhysCard]]:
    """Legal combo choices for acting player given ``hand`` and ``trick`` so far."""
    if not trick:
        return legal_leading_plays(ctx, hand)
    leader = parse_combo(ctx, list(trick[0][1]))
    return legal_follow_combo(ctx, leader, hand)


def combo_trick_sort_key(ctx: TrumpContext, pb: ParsedCombo, play_order: int) -> tuple:
    """Comparable key across seats; first-seat tie-break prefers earlier lead."""

    cores = tuple(sorted((strength_key(ctx, c, play_index=0)[:-1] for c in pb.cards), reverse=True))
    return (cores, -play_order)


def combo_trick_winner_seat(ctx: TrumpContext, trick: list[tuple[int, tuple[PhysCard, ...]]]) -> int:
    """Winning seat for a trick where each seat played a ParsedCombo-compatible bundle."""

    if not trick:
        raise ValueError("empty trick")
    parsed = [(s, parse_combo(ctx, list(cs))) for s, cs in trick]
    best_seat, best_key = parsed[0][0], combo_trick_sort_key(ctx, parsed[0][1], 0)
    for i, (seat, pb) in enumerate(parsed):
        k = combo_trick_sort_key(ctx, pb, i)
        if k > best_key:
            best_key, best_seat = k, seat
    return best_seat
