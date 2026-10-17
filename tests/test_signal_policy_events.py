import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lapse.graph import db
from lapse.signals import policy_events


def test_policy_event_disables_sms_templates_only():
    event = policy_events.load_event("x_sms_2fa_2023")
    policies = policy_events.event_policies(event)
    x = next(policy for policy in policies if policy.service.id == "x")
    google = next(policy for policy in policies if policy.service.id == "google")
    assert not any("sms_2fa" in method.needs_roles for method in x.methods)
    assert any("sms_2fa" in method.needs_roles for method in google.methods)
    assert any("totp_device" in method.needs_roles for method in x.methods)
    assert str(event.at) == "2023-03-20"
    assert "2023" in event.source_url


def test_unknown_policy_event():
    with pytest.raises(ValueError, match="Unknown policy event"):
        policy_events.load_event("not_an_event")


def test_empty_fanout(monkeypatch):
    monkeypatch.setattr(policy_events, "tenant_uids", list)
    stats = policy_events.apply_policy_event("x_sms_2fa_2023", dry_run=True)
    assert stats["tenants_scanned"] == stats["tenants_changed"] == 0
    assert stats["p95_tenant_ms"] == 0
    assert stats["total_ms"] >= 0


@pytest.fixture
def tenants(monkeypatch):
    from lapse.signals.synthetic import create_synthetic_tenants, drop_synthetic_tenants

    prefix = f"synth_test_{uuid4().hex}_"
    shared = db.graph(f"lapse:test:wp9:policy:{uuid4().hex}")
    calls = []
    monkeypatch.setitem(sys.modules, "lapse.notify", SimpleNamespace(notify=lambda *args: calls.append(args)))
    monkeypatch.setattr(db, "policy_graph", lambda: shared)
    uids = create_synthetic_tenants(20, prefix=prefix)
    monkeypatch.setattr(policy_events, "tenant_uids", lambda: uids)
    try:
        yield uids, shared, calls
    finally:
        drop_synthetic_tenants(prefix=prefix)
        if db.run(shared, "graph_node_count").rows:
            shared.delete()


@pytest.mark.db
def test_fanout_twenty_tenants_changes_only_sms_non_subscribers(tenants):
    uids, shared, notifications = tenants
    stats = policy_events.apply_policy_event("x_sms_2fa_2023")
    expected = uids[::5]
    assert stats["tenants_scanned"] == 20
    assert stats["tenants_changed"] == len(expected)
    assert stats["changed_uids"] == expected
    assert [call[0] for call in notifications] == expected
    assert 0 < stats["p95_tenant_ms"] <= stats["total_ms"]
    assert db.run(shared, "graph_node_count").rows[0]["count"] == 1
    again = policy_events.apply_policy_event("x_sms_2fa_2023")
    assert again["tenants_scanned"] == 20
    assert again["tenants_changed"] == 0
    assert len(notifications) == len(expected)


@pytest.mark.db
def test_dry_run_leaves_tenants_and_policy_untouched(tenants):
    uids, shared, notifications = tenants
    before = {uid: db.run(db.user_graph(uid), "view_methods", {"account_id": ""}).rows for uid in uids}
    stats = policy_events.apply_policy_event("x_sms_2fa_2023", dry_run=True)
    assert stats["tenants_changed"] == 4
    assert notifications == []
    assert db.run(shared, "graph_node_count").rows == []
    for uid in uids:
        assert db.run(db.user_graph(uid), "view_methods", {"account_id": ""}).rows == before[uid]
    assert policy_events.apply_policy_event("x_sms_2fa_2023")["tenants_changed"] == 4


@pytest.mark.db
def test_pending_policy_notifications_retry_after_notifier_is_installed(tenants, monkeypatch):
    uids, _, notifications = tenants
    notifier = sys.modules["lapse.notify"]
    monkeypatch.setitem(sys.modules, "lapse.notify", None)
    stats = policy_events.apply_policy_event("x_sms_2fa_2023")
    assert stats["tenants_changed"] == stats["notifications_unavailable"] == 4
    assert notifications == []
    monkeypatch.setitem(sys.modules, "lapse.notify", notifier)
    retry = policy_events.apply_policy_event("x_sms_2fa_2023")
    assert retry["tenants_changed"] == retry["notifications_unavailable"] == 0
    assert [call[0] for call in notifications] == uids[::5]


@pytest.mark.db
def test_failed_policy_notification_is_delivered_on_replay(tenants, monkeypatch):
    uids, _, notifications = tenants
    notifier = sys.modules["lapse.notify"]
    deliver = notifier.notify

    def unavailable(*args):
        raise RuntimeError("notification failed")

    monkeypatch.setattr(notifier, "notify", unavailable)
    with pytest.raises(RuntimeError, match="notification failed"):
        policy_events.apply_policy_event("x_sms_2fa_2023")
    monkeypatch.setattr(notifier, "notify", deliver)
    retry = policy_events.apply_policy_event("x_sms_2fa_2023")
    assert retry["tenants_changed"] == 3
    assert [call[0] for call in notifications] == uids[::5]
