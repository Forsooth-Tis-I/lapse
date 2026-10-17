from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from redis import Redis

from lapse.config import ROOT_DIR, settings
from lapse.contracts import Change, ChangeProcedure, ChangeStatus, ExecStep, Root, Service
from lapse.graph import db
from lapse.graph.planner import update_change


def redis_client():
    config = settings()
    return Redis(host=config.falkordb_host, port=config.falkordb_port, decode_responses=True)


def safe_component(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_:.\-]+", value) or value in {".", ".."}:
        raise ValueError("Invalid execution path component")
    return value


async def save_screenshot(page, path: Path) -> None:
    dialogs = page.get_by_role("dialog").filter(visible=True)
    target = dialogs.last if await dialogs.count() else page
    await target.screenshot(
        path=str(path),
        mask=[
            target.locator("input, textarea, [contenteditable]"),
            target.get_by_text(re.compile(r"\b\d{6}\b")),
        ],
    )
    path.chmod(0o600)


@dataclass
class StepEmitter:
    uid: str
    change_id: str
    trace: object = None
    screen_dir: Path = ROOT_DIR / "data" / "screens"
    screen_number: int = 0

    def emit(
        self,
        kind: Literal["progress", "screenshot", "need_otp", "need_user", "done", "failed"],
        message: str,
        *,
        channel: str | None = None,
        url: str | None = None,
    ) -> ExecStep:
        from lapse.events import publish
        from lapse.notify import notify

        statuses = {
            "progress": ChangeStatus.running,
            "need_otp": ChangeStatus.awaiting_otp,
            "need_user": ChangeStatus.awaiting_user,
            "done": ChangeStatus.done,
            "failed": ChangeStatus.failed,
        }
        if kind in statuses:
            rows = db.run(
                db.user_graph(self.uid), "planner_get_change", {"change_id": self.change_id}, trace=self.trace
            ).rows
            if (
                rows
                and rows[0]["change"]["status"] in {"done", "skipped", "failed"}
                and kind != rows[0]["change"]["status"]
            ):
                return ExecStep(
                    change_id=self.change_id,
                    kind=kind,
                    message=message,
                    channel=channel,
                    url=url,
                    at=datetime.now(UTC),
                )
            update_change(self.uid, self.change_id, status=statuses[kind], note=message, trace=self.trace)
        step = ExecStep(
            change_id=self.change_id,
            kind=kind,
            message=message,
            channel=channel,
            url=url,
            at=datetime.now(UTC),
        )
        publish(self.uid, "exec", step.model_dump(mode="json"))
        if kind in {"need_otp", "need_user"}:
            buttons = (
                [{"label": "Open settings", "action": "open_url", "payload": {"url": url}}] if url else []
            )
            notify(self.uid, message, buttons=buttons)
        return step

    async def screenshot(self, page, caption: str) -> str:
        self.screen_number += 1
        uid, change = safe_component(self.uid), safe_component(self.change_id)
        directory = self.screen_dir / uid
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"{change}-{self.screen_number}.png"
        await save_screenshot(page, path)
        url = f"/api/screens/{uid}/{path.name}"
        redis_client().set(f"lapse:screen:{self.uid}", json.dumps({"url": url, "caption": caption}))
        self.emit("screenshot", caption, url=url)
        return url


@dataclass
class ExecContext:
    uid: str
    change: Change
    procedure: ChangeProcedure
    service: Service
    old_root: Root
    new_root: Root | None
    started_at: datetime
    emitter: StepEmitter
    trace: object = None


class Executor(Protocol):
    def can_run(self, change: Change) -> bool: ...

    async def run(self, ctx: ExecContext) -> bool: ...
