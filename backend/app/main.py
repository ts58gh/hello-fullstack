import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.greet import build_greeting
from app.bridge.api import router as bridge_router
from app.bridge.ws import router as bridge_ws_router


def _allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    if not raw.strip():
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI()

origins = _allowed_origins()
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )


app.include_router(bridge_router)
app.include_router(bridge_ws_router)


@app.get("/")
def root() -> dict[str, str | list[str]]:
    return {
        "service": "hello-fullstack backend",
        "endpoints": [
            "/health",
            "/api/hello",
            "/api/greet?name=Ada",
            "/api/bridge/lobby",
            "/api/bridge/lobby (POST)",
            "/api/bridge/tables (POST: solo shortcut)",
            "/api/bridge/tables/{id}",
            "/api/bridge/tables/{id}/claim_seat (POST)",
            "/api/bridge/tables/{id}/release_seat (POST)",
            "/api/bridge/tables/{id}/actions (POST)",
            "/api/bridge/tables/{id}/next_deal (POST)",
            "/api/bridge/tables/{id}/ws (WS)",
        ],
        "hint": "Interactive API docs: /docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/hello")
def hello(
    name: str | None = Query(
        None,
        max_length=80,
        description="Optional name for a personalized greeting.",
    ),
) -> dict[str, str]:
    if name is None or not name.strip():
        return {"message": "Hello from FastAPI"}
    return {"message": f"Hello, {name.strip()}!"}


@app.get("/api/greet")
def greet(
    name: str | None = Query(
        None,
        max_length=80,
        description="Optional name for a personalized name card.",
    ),
) -> dict:
    return build_greeting(name)

