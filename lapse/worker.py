import importlib
import logging
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from threading import Event, Thread

from apscheduler.schedulers.background import BackgroundScheduler
from redis.exceptions import RedisError

from lapse import jobs
from lapse.config import settings

logger = logging.getLogger(__name__)
HANDLER_MODULES = ("lapse.exec.jobs", "lapse.ingest.jobs", "lapse.signals.jobs")
HANDLERS: dict[str, Callable[[str, dict], None]] = {}


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


def run() -> None:
    modules = os.environ.get("HANDLER_MODULES")
    for name in modules.split(",") if modules is not None else HANDLER_MODULES:
        name = name.strip()
        if not name:
            continue
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name and not name.startswith(f"{exc.name}."):
                raise
            logger.warning("Worker handler module %s is not installed", name)

    scheduler = BackgroundScheduler()
    scheduler.add_job(jobs.enqueue, "interval", minutes=5, args=[settings().uid, "run_detectors", {}])
    scheduler.start()
    try:
        for job in jobs.consume():
            try:
                with _keep_alive(job):
                    HANDLERS[job.kind](job.uid, job.payload)
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
