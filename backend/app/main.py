import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware


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
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )


@app.get("/")
def root() -> dict[str, str | list[str]]:
    return {
        "service": "hello-fullstack backend",
        "endpoints": ["/health", "/api/hello", "/api/hello?name=Ada"],
        "hint": "Open /health or /api/hello — try ?name= on /api/hello. Interactive API docs: /docs",
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

