"""Bridge game package.

Layers, bottom up:

- ``cards``    -- Suit, Rank, Card, deal a 52-card deck into 4 hands
- ``seats``    -- Seat enum (N/E/S/W) and partnership helpers
- ``auction``  -- Bid types and auction-rule state machine
- ``play``     -- Trick mechanics: legal plays, trick winner, dummy reveal
- ``scoring``  -- Simplified non-vulnerable contract scoring
- ``state``    -- Top-level Deal/Table state combining all phases
- ``views``    -- Per-seat redaction (hidden hands stay hidden)
- ``bots``     -- Simple but legal bidding & play bots
- ``tables``   -- In-memory store + bot-advancement loop
- ``api``      -- FastAPI router

Design rule: nothing below ``tables`` knows about HTTP, sockets, or async.
The same engine powers single-player vs bots today and will power real-time
multi-player when WebSockets are added on top of ``tables``.
"""
