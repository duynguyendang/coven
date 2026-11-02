"""Coven Cloud.

Three jobs, in order of importance:

1. take batches of events from relays and de-duplicate them by `event_id`;
2. keep a read model of projects and runs that survives event volume;
3. fan out live updates to dashboard browsers over SSE.

Nothing here executes, approves or blocks anything. That is the product
boundary, not an unfinished feature.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import events as schema
from ..redact import redact_event
from .store import build_store

HEARTBEAT_SECONDS = 5
STALE_AFTER_SECONDS = 3 * HEARTBEAT_SECONDS
DISCONNECTED_AFTER_SECONDS = 12 * HEARTBEAT_SECONDS
DEV_TOKEN = "dev"
MAX_BATCH = 500
MAX_BATCH_BYTES = 256 * 1024

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


# --------------------------------------------------------------------------- auth


def _split(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def read_tokens() -> set[str]:
    tokens = _split(os.environ.get("COVEN_READ_TOKEN")) | _split(os.environ.get("COVEN_TOKENS"))
    return tokens or {DEV_TOKEN}


def ingest_tokens() -> set[str]:
    tokens = _split(os.environ.get("COVEN_INGEST_TOKEN")) | _split(os.environ.get("COVEN_TOKENS"))
    return tokens or {DEV_TOKEN}


def any_tokens() -> set[str]:
    return read_tokens() | ingest_tokens()


def _presented(request: Request, authorization: str | None, token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if token:
        return token
    return request.query_params.get("token")


def require(scope: str):
    """Dependency factory. `scope` is `read`, `ingest` or `any`."""

    def dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
    ) -> None:
        allowed = {"read": read_tokens, "ingest": ingest_tokens, "any": any_tokens}[scope]()
        presented = _presented(request, authorization, token)
        if not presented or presented not in allowed:
            raise HTTPException(status_code=401, detail="invalid or missing token")

    return dependency


# ---------------------------------------------------------------------- payloads


class EventBatch(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    events: list[dict] = Field(default_factory=list, max_length=MAX_BATCH)


class Heartbeat(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    status: str | None = None
    stage: str | None = None
    task_id: str | None = None
    active_agents: int | None = None
    last_event_at: str | None = None


# ------------------------------------------------------------------- read model


def _epoch(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def decorate(run: dict, now: float | None = None) -> dict:
    """Add `health` and `age_seconds` so the browser does no clock maths.

    A run that stops heartbeating becomes STALE, then DISCONNECTED. It never
    stays green because the last event it sent was optimistic.
    """
    now = time.time() if now is None else now
    out = dict(run)
    stamp = run.get("last_heartbeat_at") or run.get("last_event_at")
    seen = _epoch(stamp)
    age = None if seen is None else max(0.0, round(now - seen, 1))
    out["age_seconds"] = age

    if run.get("status") != "running":
        out["health"] = str(run.get("status") or "unknown").upper()
    elif age is None or age >= DISCONNECTED_AFTER_SECONDS:
        out["health"] = "DISCONNECTED"
    elif age >= STALE_AFTER_SECONDS:
        out["health"] = "STALE"
    else:
        out["health"] = "LIVE"
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# -------------------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = build_store()
    hydrate = getattr(store, "hydrate", None)
    if hydrate is not None:
        try:
            loaded = await hydrate()
            print(f"coven cloud: rehydrated {loaded} events from DynamoDB")
        except Exception as exc:  # a failed hydrate should not stop ingest
            print(f"coven cloud: hydrate failed: {exc}")
    app.state.store = store
    app.state.started_at = _now_iso()
    if not (os.environ.get("COVEN_TOKENS") or os.environ.get("COVEN_INGEST_TOKEN")):
        print("coven cloud: using the development token 'dev'; set COVEN_TOKENS before deploying")
    yield


app = FastAPI(
    title="Coven Cloud",
    version="0.1.0",
    description="Ingest and live read models for Kiro coding-agent telemetry.",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "store": os.environ.get("COVEN_STORE", "memory"),
        "started_at": getattr(app.state, "started_at", None),
    }


@app.post("/v1/events")
async def post_events(
    request: Request,
    batch: EventBatch,
    _: None = Depends(require("ingest")),
) -> dict:
    store = request.app.state.store
    if len(json.dumps(batch.events, default=str).encode("utf-8")) > MAX_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="batch exceeds 256 KiB")
    prepared: list[dict] = []
    rejected: list[dict] = []

    for raw in batch.events:
        event = dict(raw)
        event.setdefault("project_id", batch.project_id)
        event.setdefault("run_id", batch.run_id)
        event.setdefault("source", "relay")
        event.setdefault("payload", {})
        event.setdefault("ts", _now_iso())
        if event["project_id"] != batch.project_id or event["run_id"] != batch.run_id:
            rejected.append(
                {
                    "event_id": event.get("event_id"),
                    "problems": ["event ids do not match the batch envelope"],
                }
            )
            continue
        problems = schema.validate_event(event)
        if problems:
            rejected.append({"event_id": event.get("event_id"), "problems": problems})
            continue
        prepared.append(redact_event(event))

    accepted, duplicates = await store.ingest(batch.project_id, batch.run_id, prepared)
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "received": len(batch.events),
    }


@app.post("/v1/heartbeat")
async def post_heartbeat(
    request: Request,
    body: Heartbeat,
    _: None = Depends(require("ingest")),
) -> dict:
    store = request.app.state.store
    if body.run_id not in store.runs:
        raise HTTPException(status_code=404, detail="unknown run; send events before heartbeats")
    await store.heartbeat(body.model_dump())
    return {"ok": True, "run_id": body.run_id, "at": _now_iso()}


@app.get("/v1/projects")
async def get_projects(
    request: Request,
    _: None = Depends(require("read")),
) -> dict:
    store = request.app.state.store
    projects = await store.list_projects()
    for project in projects:
        project["runs_detail"] = [
            decorate(run) for run in await store.list_runs(project["project_id"])
        ]
    return {"projects": projects}


@app.get("/v1/runs")
async def get_runs(
    request: Request,
    project_id: str | None = Query(default=None, max_length=128),
    _: None = Depends(require("read")),
) -> dict:
    store = request.app.state.store
    runs = await store.list_runs(project_id)
    return {"runs": [decorate(run) for run in runs]}


@app.get("/v1/runs/{run_id}")
async def get_run(
    request: Request,
    run_id: str,
    _: None = Depends(require("read")),
) -> dict:
    store = request.app.state.store
    run = store.runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")
    return {"run": decorate(run), "events": await store.run_events(run_id)}


@app.get("/v1/runs/{run_id}/events")
async def get_run_events(
    request: Request,
    run_id: str,
    _: None = Depends(require("read")),
) -> dict:
    store = request.app.state.store
    if run_id not in store.runs:
        raise HTTPException(status_code=404, detail="unknown run")
    return {"run_id": run_id, "events": await store.run_events(run_id)}


@app.post("/v1/events/{event_id}/dismiss")
async def dismiss_event(
    request: Request,
    event_id: str,
    _: None = Depends(require("any")),
) -> dict:
    ok = await request.app.state.store.dismiss(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="unknown event")
    return {"event_id": event_id, "dismissed": True}


@app.get("/v1/stream")
async def stream(
    request: Request,
    _: None = Depends(require("read")),
) -> StreamingResponse:
    store = request.app.state.store

    async def generate() -> AsyncIterator[bytes]:
        queue = store.subscribe()
        try:
            yield b": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                body = json.dumps(message, default=str, separators=(",", ":"))
                yield f"event: {message['kind']}\ndata: {body}\n\n".encode()
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
