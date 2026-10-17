import sys
from types import ModuleType

from lapse.signals import detectors, jobs


def test_handler_runs_for_requested_tenant(monkeypatch):
    calls = []
    monkeypatch.setattr(
        detectors, "run_detectors", lambda uid, **kwargs: calls.append((uid, kwargs)) or ["signal"]
    )
    assert jobs.handle_run_detectors("tenant", {"now": "2026-10-17"}) == ["signal"]
    assert calls == [("tenant", {"now": "2026-10-17"})]


def test_all_tenants_and_lazy_registration(monkeypatch):
    tenants = ModuleType("lapse.signals.tenants")
    tenants.tenant_uids = lambda: ["one", "two"]
    monkeypatch.setitem(sys.modules, "lapse.signals.tenants", tenants)
    monkeypatch.setattr(detectors, "run_detectors", lambda uid, **kwargs: [uid])
    assert jobs.run_all_detectors(now="2026-10-17") == {"one": ["one"], "two": ["two"]}
    worker = ModuleType("lapse.worker")
    registry = {}
    worker.handler = lambda kind: lambda function: registry.setdefault(kind, function)
    monkeypatch.setitem(sys.modules, "lapse.worker", worker)
    jobs.register_handlers()
    assert registry == {"run_detectors": jobs.handle_run_detectors}
