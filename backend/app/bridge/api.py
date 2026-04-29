"""FastAPI router for the bridge game.

Two routers are exported:

- ``router``    -- HTTP REST endpoints under ``/api/bridge``
- ``ws_router`` -- WebSocket endpoint under ``/api/bridge/tables/{id}/ws``

The HTTP endpoints handle table creation, lobby listing, seat
claim/release, and a synchronous fallback for actions / next-deal. The
WebSocket endpoint is the primary real-time channel: every state
mutation (regardless of source) is fanned out to every connected socket.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import lobby as lobby_mod
from . import tables
from .seats import SEAT_ORDER, Seat
from .views import view_for
from .ws import router as ws_router  # noqa: F401  -- re-exported below


router = APIRouter(prefix="/api/bridge", tags=["bridge"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class HostInfo(BaseModel):
    client_id: Optional[str] = None
    display_name: Optional[str] = None


class CreateLobbyRequest(BaseModel):
    mode: str = Field(default="with_bots", description="with_bots | humans_only")
    host: HostInfo = Field(default_factory=HostInfo)
    host_seat: Optional[str] = Field(default=None, description="N/E/S/W or null")
    seed: Optional[int] = None
    public: bool = True


class CreateLobbyResponse(BaseModel):
    table_id: str
    seat: Optional[str]
    token: Optional[str]
    state: dict[str, Any]


class CreateTableRequest(BaseModel):
    """Legacy solo shortcut body."""

    seed: Optional[int] = None
    display_name: Optional[str] = None
    client_id: Optional[str] = None


class CreateTableResponse(BaseModel):
    table_id: str
    seat: str
    token: str
    state: dict[str, Any]


class ClaimSeatRequest(BaseModel):
    client_id: Optional[str] = None
    display_name: Optional[str] = None
    seat: str


class ClaimSeatResponse(BaseModel):
    table_id: str
    seat: str
    token: str
    state: dict[str, Any]


class ReleaseSeatRequest(BaseModel):
    token: str


class ActionRequest(BaseModel):
    token: str
    action: dict[str, Any]


class ActionResponse(BaseModel):
    events: list[dict[str, Any]]
    state: dict[str, Any]


class NextDealRequest(BaseModel):
    token: str
    seed: Optional[int] = None


# ---------------------------------------------------------------------------
# Lobby
# ---------------------------------------------------------------------------


@router.get("/lobby")
async def get_lobby() -> dict:
    items = await lobby_mod.list_lobby()
    return {"tables": items}


@router.post("/lobby", response_model=CreateLobbyResponse)
async def post_lobby(body: CreateLobbyRequest) -> CreateLobbyResponse:
    seat: Optional[Seat] = None
    if body.host_seat:
        try:
            seat = Seat(body.host_seat)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid seat") from None
    if body.mode not in ("with_bots", "humans_only"):
        raise HTTPException(status_code=400, detail="mode must be with_bots or humans_only")

    try:
        table, token = await lobby_mod.create_table(
            mode=body.mode,  # type: ignore[arg-type]
            host_client_id=body.host.client_id,
            host_display_name=body.host.display_name,
            host_seat=seat,
            public=body.public,
            seed=body.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    state = view_for(table, seat) if seat is not None else table.lobby_summary()
    return CreateLobbyResponse(
        table_id=table.id,
        seat=seat.value if seat is not None else None,
        token=token,
        state=state,
    )


# ---------------------------------------------------------------------------
# Legacy solo shortcut (kept so the original single-player flow is unchanged)
# ---------------------------------------------------------------------------


@router.post("/tables", response_model=CreateTableResponse)
async def post_tables_solo(body: Optional[CreateTableRequest] = None) -> CreateTableResponse:
    seed = body.seed if body else None
    display_name = (body.display_name if body else None) or "You"
    client_id = body.client_id if body else None
    table, token = await tables.create_solo_table(
        human_seat=Seat.SOUTH,
        seed=seed,
        display_name=display_name,
        client_id=client_id,
    )
    state = view_for(table, Seat.SOUTH)
    return CreateTableResponse(
        table_id=table.id, seat=Seat.SOUTH.value, token=token, state=state
    )


# ---------------------------------------------------------------------------
# Per-table interaction
# ---------------------------------------------------------------------------


@router.get("/tables/{table_id}")
async def get_state(table_id: str, token: str = Query(..., min_length=4)) -> dict[str, Any]:
    try:
        table = tables.get_table(table_id)
        seat = tables.find_seat_for_token(table, token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    return view_for(table, seat)


@router.post("/tables/{table_id}/claim_seat", response_model=ClaimSeatResponse)
async def post_claim_seat(table_id: str, body: ClaimSeatRequest) -> ClaimSeatResponse:
    try:
        seat = Seat(body.seat)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid seat") from None
    try:
        token = await lobby_mod.claim_seat(table_id, seat, body.client_id, body.display_name)
        table = tables.get_table(table_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return ClaimSeatResponse(
        table_id=table_id, seat=seat.value, token=token, state=view_for(table, seat)
    )


@router.post("/tables/{table_id}/release_seat")
async def post_release_seat(table_id: str, body: ReleaseSeatRequest) -> dict:
    seat = await lobby_mod.release_seat(table_id, body.token)
    return {"released": seat.value if seat else None}


@router.post("/tables/{table_id}/actions", response_model=ActionResponse)
async def post_action(table_id: str, body: ActionRequest) -> ActionResponse:
    try:
        result = await tables.submit_action(table_id, body.token, body.action)
        table = tables.get_table(table_id)
        seat = tables.find_seat_for_token(table, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return ActionResponse(events=result["events"], state=view_for(table, seat))


@router.post("/tables/{table_id}/next_deal", response_model=ActionResponse)
async def post_next_deal(table_id: str, body: NextDealRequest) -> ActionResponse:
    try:
        result = await tables.start_next_deal(table_id, body.token, seed=body.seed)
        table = tables.get_table(table_id)
        seat = tables.find_seat_for_token(table, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return ActionResponse(events=result["events"], state=view_for(table, seat))
