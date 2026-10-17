from __future__ import annotations


def handle_run_detectors(uid: str, payload: dict) -> list:
    from lapse.signals.detectors import run_detectors

    return run_detectors(uid, now=payload.get("now"))


def run_all_detectors(*, now=None) -> dict[str, list]:
    from lapse.signals.detectors import run_detectors
    from lapse.signals.tenants import tenant_uids

    return {uid: run_detectors(uid, now=now) for uid in tenant_uids()}


def register_handlers() -> None:
    from lapse.worker import handler

    handler("run_detectors")(handle_run_detectors)
