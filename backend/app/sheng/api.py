"""HTTP REST for ``ShengRoom`` (+ re-export WS router like bridge.api)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import tables
from .cards import Suit
from .friend import FriendCall
from .views import view_for
from .ws import router as ws_router  # noqa: F401 — re-exported for main


router = APIRouter(prefix="/api/sheng", tags=["sheng"])


class FriendCallSpec(BaseModel):
    nth: int = Field(ge=1, le=1080)
    suit: Literal["C", "D", "H", "S"]
    rank: int = Field(ge=2, le=14)


def _calls_from_specs(items: Optional[list[FriendCallSpec]]) -> tuple[FriendCall, ...]:
    if not items:
        return ()
    return tuple(FriendCall(nth=i.nth, suit=Suit(i.suit), rank=i.rank) for i in items)


class CreateTableBody(BaseModel):
    num_players: Literal[4, 6] = Field(default=4)
    seed: Optional[int] = None
    declarer_seat: int = Field(default=0, ge=0)
    match_level_rank: int = Field(default=5, ge=5, le=14)
    friend_calls: Optional[list[FriendCallSpec]] = None


class CreateTableResponse(BaseModel):
    table_id: str
    tokens: dict[str, str]
    state_seat_0: dict[str, Any]


class PlayBody(BaseModel):
    token: str = Field(..., min_length=4)
    card_id: Optional[int] = None
    card_ids: Optional[list[int]] = None


class PlayResponse(BaseModel):
    events: list[dict[str, Any]]
    state: dict[str, Any]


class NextHandBody(BaseModel):
    token: str = Field(..., min_length=4)
    seed: Optional[int] = None
    friend_calls: Optional[list[FriendCallSpec]] = None


class NextHandResponse(BaseModel):
    events: list[dict[str, Any]]
    state: dict[str, Any]


class DeclareBody(BaseModel):
    token: str = Field(..., min_length=4)
    action: Literal["pass", "bid_suit", "bid_nt"]
    suit: Optional[Literal["C", "D", "H", "S"]] = None


class DeclareResponse(BaseModel):
    events: list[dict[str, Any]]
    state: dict[str, Any]


@router.post("/tables", response_model=CreateTableResponse)
async def create_table(body: Optional[CreateTableBody] = None) -> CreateTableResponse:
    b = body or CreateTableBody()
    if b.num_players not in (4, 6):
        raise HTTPException(status_code=400, detail="num_players must be 4 or 6")
    if not (0 <= b.declarer_seat < b.num_players):
        raise HTTPException(status_code=400, detail="invalid declarer_seat")

    fc: tuple[FriendCall, ...] = ()
    if b.friend_calls is not None:
        fc = _calls_from_specs(b.friend_calls)
    try:
        tables.validate_friend_calls(b.num_players, fc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    room, toks = await tables.create_room(
        num_players=b.num_players,
        seed=b.seed,
        declarer_seat=b.declarer_seat,
        match_level_rank=b.match_level_rank,
        friend_calls=fc,
    )
    tok_str = {str(k): v for k, v in toks.items()}
    return CreateTableResponse(
        table_id=room.id,
        tokens=tok_str,
        state_seat_0=view_for(room, 0),
    )


@router.post("/tables/{table_id}/declare", response_model=DeclareResponse)
async def post_declare(table_id: str, body: DeclareBody) -> DeclareResponse:
    payload: dict[str, Any] = {"action": body.action}
    if body.action == "bid_suit":
        if body.suit is None:
            raise HTTPException(status_code=400, detail="suit required for bid_suit")
        payload["suit"] = body.suit
    try:
        out = await tables.submit_declare(table_id, body.token, payload)
        room = tables.get_room(table_id)
        seat = tables.find_seat_for_token(room, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return DeclareResponse(events=out.get("events") or [], state=view_for(room, seat))


@router.get("/tables/{table_id}")
async def get_state(table_id: str, token: str = Query(..., min_length=4)) -> dict[str, Any]:
    try:
        room = tables.get_room(table_id)
        seat = tables.find_seat_for_token(room, token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    return view_for(room, seat)


@router.post("/tables/{table_id}/actions", response_model=PlayResponse)
async def post_play(table_id: str, body: PlayBody) -> PlayResponse:
    ids = body.card_ids
    if ids is None or len(ids) == 0:
        if body.card_id is None:
            raise HTTPException(status_code=400, detail="card_ids or card_id required") from None
        ids = [body.card_id]
    try:
        out = await tables.submit_play(table_id, body.token, [int(x) for x in ids])
        room = tables.get_room(table_id)
        seat = tables.find_seat_for_token(room, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return PlayResponse(events=out.get("events") or [], state=view_for(room, seat))


@router.post("/tables/{table_id}/next_hand", response_model=NextHandResponse)
async def post_next_hand(table_id: str, body: NextHandBody) -> NextHandResponse:
    try:
        room = tables.get_room(table_id)
        seat = tables.find_seat_for_token(room, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None

    try:
        fc_opt: tuple[FriendCall, ...] | None = None
        if body.friend_calls is not None:
            fc_opt = _calls_from_specs(body.friend_calls)
        await tables.start_next_hand(table_id, seed=body.seed, friend_calls=fc_opt)
        room = tables.get_room(table_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return NextHandResponse(
        events=[{"type": "next_hand"}],
        state=view_for(room, seat),
    )
