import os

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.greet import build_greeting
from app.bridge.api import router as bridge_router
from app.bridge.ws import router as bridge_ws_router
from app.sheng.api import router as sheng_router
from app.sheng.ws import router as sheng_ws_router


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
app.include_router(sheng_router)
app.include_router(sheng_ws_router)

_SHENG_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "sheng"
if (_SHENG_FRONTEND / "index.html").is_file():
    app.mount(
        "/sheng",
        StaticFiles(directory=str(_SHENG_FRONTEND), html=True),
        name="sheng_frontend",
    )


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
            "/api/sheng/tables (POST)",
            "/api/sheng/tables/{id}",
            "/api/sheng/tables/{id}/next_hand (POST)",
            "/api/sheng/tables/{id}/ws (WS)",
            "/sheng/ (tractor play UI, when frontend/sheng present)",
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

