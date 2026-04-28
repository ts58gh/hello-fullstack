"""FastAPI router for the bridge game."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .seats import Seat, SEAT_ORDER
from .tables import (
    create_solo_table,
    find_seat_for_token,
    get_table,
    start_next_deal,
    submit_action,
)
from .views import view_for


router = APIRouter(prefix="/api/bridge", tags=["bridge"])


class CreateTableRequest(BaseModel):
    seed: int | None = Field(default=None, description="Optional deterministic seed for the deal.")


class CreateTableResponse(BaseModel):
    table_id: str
    seat: str
    token: str
    state: dict[str, Any]


class ActionRequest(BaseModel):
    token: str
    action: dict[str, Any]


class ActionResponse(BaseModel):
    events: list[dict[str, Any]]
    state: dict[str, Any]


class NextDealRequest(BaseModel):
    token: str
    seed: int | None = None


@router.post("/tables", response_model=CreateTableResponse)
def create_table(body: CreateTableRequest | None = None) -> CreateTableResponse:
    seed = body.seed if body else None
    table, token = create_solo_table(human_seat=Seat.SOUTH, seed=seed)
    # Run bots up to the human's first action (e.g. dealer is North).
    from .tables import _advance_bots, _lock_for  # local import to avoid cycle
    with _lock_for(table.id):
        events = _advance_bots(table)
    state = view_for(table, Seat.SOUTH)
    state["pending_events"] = events
    return CreateTableResponse(table_id=table.id, seat=Seat.SOUTH.value, token=token, state=state)


@router.get("/tables/{table_id}")
def get_state(table_id: str, token: str = Query(..., min_length=4)) -> dict[str, Any]:
    try:
        table = get_table(table_id)
        seat = find_seat_for_token(table, token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    return view_for(table, seat)


@router.post("/tables/{table_id}/actions", response_model=ActionResponse)
def post_action(table_id: str, body: ActionRequest) -> ActionResponse:
    try:
        events = submit_action(table_id, body.token, body.action)
        table = get_table(table_id)
        seat = find_seat_for_token(table, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return ActionResponse(events=events["events"], state=view_for(table, seat))


@router.post("/tables/{table_id}/next_deal", response_model=ActionResponse)
def post_next_deal(table_id: str, body: NextDealRequest) -> ActionResponse:
    try:
        events = start_next_deal(table_id, body.token, seed=body.seed)
        table = get_table(table_id)
        seat = find_seat_for_token(table, body.token)
    except KeyError:
        raise HTTPException(status_code=404, detail="table not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return ActionResponse(events=events["events"], state=view_for(table, seat))
