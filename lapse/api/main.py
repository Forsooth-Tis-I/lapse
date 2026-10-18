from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
from contextlib import nullcontext
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated
from urllib.parse import quote

import yaml
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sse_starlette.sse import EventSourceResponse

from lapse import events, jobs, otp, telegram_link
from lapse.api import inboxes
from lapse.api.models import (
    ChatInput,
    GraphData,
    GraphStats,
    IngestInput,
    OnboardingInput,
    OtpInput,
    PlanInput,
    ScenarioInput,
)
from lapse.config import ROOT_DIR, settings
from lapse.contracts import Change, ChangeStatus, Explanation, Plan, Root, ScenarioResult, ToolCallRecord

DATA_DIR = ROOT_DIR / "data"
app = FastAPI(title="Lapse API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Lapse-Uid"],
)


def current_uid(x_lapse_uid: Annotated[str | None, Header(min_length=1)] = None) -> str:
    return settings().uid if x_lapse_uid is None else x_lapse_uid


Uid = Annotated[str, Depends(current_uid)]


def writable() -> None:
    if settings().demo_mode:
        raise HTTPException(
            403, "This demo is read-only. Run Lapse locally to connect accounts or make changes."
        )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": error["loc"], "msg": "Invalid value", "type": error["type"]} for error in exc.errors()
            ]
        },
    )


@app.exception_handler(RedisConnectionError)
@app.exception_handler(RedisTimeoutError)
async def redis_unavailable(request: Request, exc: Exception):
    return JSONResponse(
        status_code=503, content={"detail": "Lapse storage is unavailable. Please try again."}
    )


def load(module: str):
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        raise HTTPException(
            503, "This Lapse component is not available yet. Please try again later."
        ) from exc


def graph_call(uid: str, module: str, name: str, *args, audit_args=None, **kwargs):
    function = getattr(load(module), name)
    try:
        trace_module = importlib.import_module("lapse.trace")
    except ModuleNotFoundError as exc:
        if exc.name != "lapse.trace":
            raise HTTPException(503, "Query tracing is unavailable. Please try again later.") from exc
        context = nullcontext(None)
    else:
        context = trace_module.tool_call(uid, name, audit_args or {})
    try:
        with context as trace:
            if "trace" in inspect.signature(function).parameters:
                kwargs["trace"] = trace
            result = function(uid, *args, **kwargs)
            return asyncio.run(result) if inspect.isawaitable(result) else result
    except KeyError as exc:
        raise HTTPException(404, "The requested item does not exist for this user.") from exc
    except ValueError as exc:
        raise HTTPException(422, "The request is not valid for the current graph.") from exc


def found(value, kind: str):
    if value is None:
        raise HTTPException(404, f"That {kind} does not exist for this user.")
    return value


def find_change(uid: str, change_id: str) -> Change:
    plans = graph_call(uid, "lapse.graph.planner", "list_plans")
    return found(
        next((step for plan in plans for step in plan.steps if step.id == change_id), None), "change"
    )


def require_roots(uid: str, root_ids: list[str]) -> None:
    known = {root.id for root in graph_call(uid, "lapse.graph.views", "list_roots")}
    if any(root_id not in known for root_id in root_ids):
        raise HTTPException(404, "A requested root does not exist for this user.")


@app.get("/api/roots", response_model=list[Root])
def roots(uid: Uid):
    return graph_call(uid, "lapse.graph.views", "list_roots")


@app.get("/api/graph", response_model=GraphData, response_model_exclude_none=True)
def graph(uid: Uid, scenario: str | None = None):
    if scenario is not None:
        found(
            graph_call(
                uid, "lapse.graph.scenarios", "get_scenario", scenario, audit_args={"scenario_id": scenario}
            ),
            "scenario",
        )
    return graph_call(
        uid, "lapse.graph.views", "graph_view", scenario_id=scenario, audit_args={"scenario_id": scenario}
    )


@app.post("/api/scenarios", response_model=ScenarioResult)
def create_scenario(body: ScenarioInput, uid: Uid):
    require_roots(uid, body.root_ids)
    return graph_call(
        uid, "lapse.graph.scenarios", "run_scenario", body, audit_args=body.model_dump(mode="json")
    )


@app.get("/api/scenarios/{id}", response_model=ScenarioResult)
def scenario(id: str, uid: Uid):
    return found(
        graph_call(uid, "lapse.graph.scenarios", "get_scenario", id, audit_args={"scenario_id": id}),
        "scenario",
    )


@app.get("/api/scenarios/{id}/explain/{account_id}", response_model=Explanation)
def explain(id: str, account_id: str, uid: Uid):
    scenario(id, uid)
    result = graph_call(
        uid,
        "lapse.graph.scenarios",
        "explain",
        id,
        account_id,
        audit_args={"scenario_id": id, "account_id": account_id},
    )
    if result.outcome == "not_in_graph":
        raise HTTPException(404, "That account is not in this user's graph.")
    return result


@app.post("/api/plans", response_model=Plan)
def create_plan(body: PlanInput, uid: Uid):
    require_roots(uid, [body.old_root] + ([body.new_root] if body.new_root is not None else []))
    args = body.model_dump(mode="json")
    return graph_call(uid, "lapse.graph.planner", "plan_for_root", **body.model_dump(), audit_args=args)


@app.get("/api/plans", response_model=list[Plan])
def plans(uid: Uid):
    return graph_call(uid, "lapse.graph.planner", "list_plans")


@app.get("/api/plans/{id}", response_model=Plan)
def plan(id: str, uid: Uid):
    return found(graph_call(uid, "lapse.graph.planner", "get_plan", id, audit_args={"plan_id": id}), "plan")


@app.post("/api/changes/{id}/approve", response_model=Change, dependencies=[Depends(writable)])
def approve(id: str, uid: Uid):
    change = find_change(uid, id)
    if change.status not in (ChangeStatus.proposed, ChangeStatus.failed, ChangeStatus.approved):
        return change
    change = graph_call(
        uid,
        "lapse.graph.planner",
        "update_change",
        id,
        status=ChangeStatus.approved,
        audit_args={"change_id": id, "status": "approved"},
    )
    jobs.enqueue(uid, "execute_change", {"change_id": id})
    return change


@app.post("/api/changes/{id}/otp", response_model=Change, dependencies=[Depends(writable)])
def submit_otp(id: str, body: OtpInput, uid: Uid):
    change = find_change(uid, id)
    otp.submit(uid, id, body.code.get_secret_value())
    return change


@app.get("/api/trace", response_model=list[ToolCallRecord])
def trace(uid: Uid, since: datetime | None = None):
    return graph_call(
        uid,
        "lapse.trace",
        "list_trace",
        since=since,
        audit_args={"since": since.isoformat() if since else None},
    )


@app.get("/api/agent/screen")
def screen(request: Request, uid: Uid):
    path = jobs.client().get(f"lapse:screen:{uid}")
    if path is None:
        return {"url": None, "caption": "No screenshot yet.", "mock": False}
    if isinstance(path, bytes):
        path = path.decode()
    caption = "Latest executor screenshot"
    try:
        pointer = json.loads(path)
    except json.JSONDecodeError:
        name = Path(path).name
    else:
        if not isinstance(pointer, dict) or not isinstance(pointer.get("url"), str):
            raise HTTPException(404, "That screenshot is not available.")
        prefix = f"/api/screens/{uid}/"
        if not pointer["url"].startswith(prefix):
            raise HTTPException(404, "That screenshot is not available.")
        name = pointer["url"][len(prefix) :]
        caption = pointer.get("caption", caption)
    screenshot_path(uid, name)
    return {
        "url": str(request.url_for("screenshot", screen_uid=uid, name=name)),
        "caption": caption,
        "mock": False,
    }


def screenshot_path(uid: str, name: str) -> Path:
    from lapse.exec.base import safe_component

    try:
        safe_component(uid)
        safe_component(name)
    except ValueError as exc:
        raise HTTPException(404, "That screenshot is not available.") from exc
    directory = (DATA_DIR / "screens").resolve() / uid
    path = (directory / name).resolve()
    if (
        directory.is_symlink()
        or path.parent != directory
        or not path.is_file()
        or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    ):
        raise HTTPException(404, "That screenshot is not available.")
    return path


@app.get("/api/screens/{screen_uid}/{name}")
def screenshot(screen_uid: str, name: str, uid: Uid):
    if screen_uid != uid:
        raise HTTPException(404, "That screenshot is not available.")
    return FileResponse(screenshot_path(uid, name))


@app.get("/api/screens/{name}")
def legacy_screenshot(name: str, uid: Uid):
    return FileResponse(screenshot_path(uid, name))


@app.get("/api/keystones")
def keystones(uid: Uid, limit: int = 3):
    return graph_call(
        uid, "lapse.graph.algorithms", "keystones", max(1, min(limit, 10)), audit_args={"limit": limit}
    )


@app.get("/api/path")
def path(uid: Uid, from_id: str, to_id: str):
    return graph_call(
        uid,
        "lapse.graph.algorithms",
        "shortest_path",
        from_id,
        to_id,
        audit_args={"from_id": from_id, "to_id": to_id},
    )


@app.get("/api/stats", response_model=GraphStats)
def stats(uid: Uid):
    return graph_call(uid, "lapse.graph.views", "stats")


@app.post("/api/onboarding", dependencies=[Depends(writable)])
def onboard(body: OnboardingInput, uid: Uid):
    load("lapse.onboarding")
    cipher = None
    if body.inboxes:
        try:
            cipher = Fernet(settings().secret_key.encode())
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                503, "Inbox encryption is not configured. Set LAPSE_SECRET_KEY locally."
            ) from exc
    persona = body.model_dump(mode="json", exclude={"inboxes", "phones"}, exclude_none=True)
    persona["phones"] = []
    for phone in body.phones:
        value = phone.model_dump(mode="json", exclude={"number"}, exclude_none=True)
        value["id"] = phone.id or f"phone_{sha256(phone.number.encode()).hexdigest()[:16]}"
        value["e164"] = phone.number
        persona["phones"].append(value)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w+", suffix=".yaml", dir=DATA_DIR) as temporary:
        yaml.safe_dump(persona, temporary)
        temporary.flush()
        graph_call(
            uid,
            "lapse.onboarding",
            "load_persona_local",
            path=temporary.name,
            audit_args={"phones": len(body.phones), "emails": len(body.emails), "devices": len(body.devices)},
        )
    if cipher is not None:
        try:
            inboxes.store(uid, body.inboxes, DATA_DIR, cipher)
        except InvalidToken as exc:
            raise HTTPException(
                503, "Stored inboxes could not be decrypted. Check LAPSE_SECRET_KEY locally."
            ) from exc
    return telegram_code(uid)


def telegram_code(uid: str) -> dict:
    code = telegram_link.new_link_code(uid)
    bot = os.environ.get("TELEGRAM_BOT_USERNAME", "LapseAlfredBot").lstrip("@")
    return {"telegram_code": code, "telegram_url": f"https://t.me/{quote(bot, safe='')}?start={quote(code)}"}


@app.post("/api/telegram/link", dependencies=[Depends(writable)])
def telegram_link_code(uid: Uid):
    return telegram_code(uid)


@app.post("/api/ingest/run", dependencies=[Depends(writable)])
def ingest(uid: Uid, body: IngestInput | None = None):
    jobs.enqueue(uid, "ingest_run", body.model_dump(exclude_none=True) if body else {})
    return {"started": True}


@app.post("/api/chat", dependencies=[Depends(writable)])
def chat(body: ChatInput, uid: Uid):
    return graph_call(uid, "lapse.agent.agent", "respond", body.text, channel="web")


@app.get("/api/events")
async def event_stream(uid: Uid):
    async def frames():
        async for event in events.subscribe(uid):
            yield {"event": event.type, "data": event.model_dump_json()}

    return EventSourceResponse(frames())


def run() -> None:
    import uvicorn

    uvicorn.run("lapse.api.main:app", host="127.0.0.1", port=8000)
