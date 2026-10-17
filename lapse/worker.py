import asyncio
import importlib
import inspect
import logging
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from threading import Event, Thread

from apscheduler.schedulers.background import BackgroundScheduler
from redis.exceptions import RedisError

from lapse import jobs

logger = logging.getLogger(__name__)
HANDLER_MODULES = ("lapse.exec.jobs", "lapse.ingest.jobs", "lapse.signals.jobs")
HANDLERS: dict[str, Callable[[str, dict], object]] = {}


def handler(kind: str):
    def register(function):
        HANDLERS[kind] = function
        return function

    return register


@contextmanager
def _keep_alive(job: jobs.Job):
    stopped = Event()

    def renew():
        while not stopped.wait(jobs.RECLAIM_AFTER_MS / 3000):
            try:
                if not job.renew_lease():
                    return
            except RedisError:
                logger.warning("Could not renew job %s lease", job.id)

    thread = Thread(target=renew, name=f"lapse-job-{job.id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


@handler("verify_pending")
def handle_verify_pending(uid: str, payload: dict):
    from lapse.exec.verify import verify_pending

    return verify_pending(uid)


def dispatch_job(uid: str, kind: str, payload: dict):
    result = HANDLERS[kind](uid, payload)
    if inspect.isawaitable(result):

        async def finish():
            return await result

        result = asyncio.run(finish())
    if kind == "ingest_run":
        handle_verify_pending(uid, {})
    return result


def enqueue_periodic_jobs() -> None:
    from lapse.signals.tenants import tenant_uids

    for uid in tenant_uids():
        jobs.enqueue(uid, "run_detectors", {})
        jobs.enqueue(uid, "verify_pending", {})


def load_handlers() -> None:
    modules = os.environ.get("HANDLER_MODULES")
    for name in modules.split(",") if modules is not None else HANDLER_MODULES:
        name = name.strip()
        if not name:
            continue
        try:
            module = importlib.import_module(name)
            register = getattr(module, "register_handlers", None)
            if register is not None:
                register()
        except ModuleNotFoundError as exc:
            if exc.name != name and not name.startswith(f"{exc.name}."):
                raise
            logger.warning("Worker handler module %s is not installed", name)

    handler("verify_pending")(handle_verify_pending)


def run() -> None:
    from lapse.exec.t4_offline import register_reminders

    load_handlers()
    scheduler = BackgroundScheduler()
    scheduler.add_job(enqueue_periodic_jobs, "interval", minutes=5, id="tenant_checks")
    register_reminders(scheduler)
    scheduler.start()
    try:
        for job in jobs.consume():
            try:
                with _keep_alive(job):
                    dispatch_job(job.uid, job.kind, job.payload)
            except Exception:  # noqa: BLE001 - retry handlers without logging secret-bearing exceptions
                logger.warning("Job %s (%s) failed on attempt %s", job.id, job.kind, job.attempts)
                job.retry()
            else:
                job.ack()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    sys.modules["lapse.worker"] = sys.modules[__name__]
    run()
