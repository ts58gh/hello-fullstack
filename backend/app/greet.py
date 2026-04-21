"""Fancy greeting logic.

Everything here is deterministic from the input name (plus today's date for the
fortune), so the backend needs no external network calls or databases.
"""

from __future__ import annotations

import colorsys
import hashlib
import html
from datetime import date, timezone, datetime


GREETINGS: list[tuple[str, str]] = [
    ("English", "Hello, {name}!"),
    ("Spanish", "\u00a1Hola, {name}!"),
    ("French", "Bonjour, {name} !"),
    ("German", "Hallo, {name}!"),
    ("Italian", "Ciao, {name}!"),
    ("Portuguese", "Ol\u00e1, {name}!"),
    ("Dutch", "Hallo, {name}!"),
    ("Japanese", "\u3053\u3093\u306b\u3061\u306f\u3001{name}\u3055\u3093\uff01"),
    ("Chinese", "\u4f60\u597d\uff0c{name}\uff01"),
    ("Korean", "\uc548\ub155\ud558\uc138\uc694, {name}\ub2d8!"),
    ("Hindi", "\u0928\u092e\u0938\u094d\u0924\u0947, {name}!"),
    ("Arabic", "\u0645\u0631\u062d\u0628\u0627 \u064a\u0627 {name}!"),
    ("Russian", "\u041f\u0440\u0438\u0432\u0435\u0442, {name}!"),
    ("Greek", "\u0393\u03b5\u03b9\u03b1 \u03c3\u03bf\u03c5, {name}!"),
    ("Swahili", "Habari, {name}!"),
    ("Hawaiian", "Aloha, {name}!"),
    ("Klingon", "nuqneH, {name}!"),
]

AURA_WORDS: list[str] = [
    "Radiant", "Electric", "Cosmic", "Serene", "Bold",
    "Mystical", "Vibrant", "Gentle", "Fierce", "Luminous",
    "Playful", "Stoic", "Whimsical", "Ambitious", "Curious",
    "Chill", "Tenacious", "Kindred", "Bright", "Unhurried",
]

FORTUNES: list[str] = [
    "A quiet breakthrough is closer than you think.",
    "Today's small step rewrites tomorrow's map.",
    "Your next idea will surprise you \u2014 write it down.",
    "Someone will quote your words this week.",
    "Say yes to the weird one.",
    "Rest is a feature, not a bug.",
    "You'll spot a pattern no one else has seen.",
    "An unexpected message brings good news.",
    "Trade one hour of scrolling for one hour of making.",
    "Your curiosity is a compass \u2014 follow it.",
    "Ship the small thing. The big thing is waiting for it.",
    "Someone you haven't met yet is rooting for you.",
    "The boring path contains a hidden door.",
    "Today is a good day to fix one old bug.",
    "Ask a better question and the day opens up.",
    "Kindness today will echo back on a Tuesday.",
    "You are allowed to change your mind in public.",
    "Start messy. Finish clean.",
    "The calm voice in your head is usually right.",
    "One deep breath is a legal cheat code.",
]

_LEET = str.maketrans({
    "a": "4", "A": "4",
    "e": "3", "E": "3",
    "i": "1", "I": "1",
    "o": "0", "O": "0",
    "s": "5", "S": "5",
    "t": "7", "T": "7",
    "b": "8", "B": "8",
    "g": "9", "G": "9",
})
_VOWELS = set("aeiouyAEIOUY")


def _digest(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def _pick(items: list, digest: bytes, offset: int):
    idx = digest[offset % len(digest)] % len(items)
    return items[idx]


def _hex_from_hsl(hue: float, sat: float, light: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, light, sat)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        w = parts[0]
        return (w[0] + (w[1] if len(w) > 1 else "")).upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _svg_avatar(name: str, color_a: str, color_b: str) -> str:
    initials = html.escape(_initials(name))
    # SVG string kept compact; safe because only color hexes and escaped initials are interpolated.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="100%" height="100%" role="img" aria-label="Monogram">'
        '<defs>'
        '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{color_a}"/>'
        f'<stop offset="100%" stop-color="{color_b}"/>'
        '</linearGradient>'
        '<radialGradient id="s" cx="30%" cy="25%" r="60%">'
        '<stop offset="0%" stop-color="white" stop-opacity="0.35"/>'
        '<stop offset="100%" stop-color="white" stop-opacity="0"/>'
        '</radialGradient>'
        '</defs>'
        '<rect width="256" height="256" rx="48" fill="url(#g)"/>'
        '<rect width="256" height="256" rx="48" fill="url(#s)"/>'
        '<text x="50%" y="55%" text-anchor="middle" dominant-baseline="middle" '
        'font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif" '
        'font-weight="700" font-size="108" fill="white" fill-opacity="0.96" '
        f'letter-spacing="-2">{initials}</text>'
        '</svg>'
    )


def build_greeting(name: str | None) -> dict:
    safe = (name or "").strip() or "friend"

    static_digest = _digest(safe.lower())
    today = date.today().isoformat()
    daily_digest = _digest(f"{safe.lower()}|{today}")

    greetings = [
        {"lang": lang, "text": tmpl.format(name=safe)}
        for lang, tmpl in GREETINGS
    ]

    letters = [c for c in safe if c.isalpha()]
    stats = {
        "length": len(safe),
        "letters": len(letters),
        "vowels": sum(1 for c in letters if c in _VOWELS),
        "consonants": sum(1 for c in letters if c not in _VOWELS),
        "reversed": safe[::-1],
        "leet": safe.translate(_LEET),
    }

    hue_a = static_digest[0] * 360 // 256
    hue_b = (hue_a + 30 + (static_digest[1] % 80)) % 360
    sat = 0.68 + (static_digest[2] % 25) / 100.0
    light = 0.52 + (static_digest[3] % 10) / 100.0
    color_a = _hex_from_hsl(hue_a, sat, light)
    color_b = _hex_from_hsl(hue_b, sat, max(0.42, light - 0.08))
    aura_word = _pick(AURA_WORDS, static_digest, 4)

    fortune = _pick(FORTUNES, daily_digest, 0)

    return {
        "name": safe,
        "greetings": greetings,
        "stats": stats,
        "aura": {"colors": [color_a, color_b], "word": aura_word},
        "fortune": fortune,
        "avatar_svg": _svg_avatar(safe, color_a, color_b),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
