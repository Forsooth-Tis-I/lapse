from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from lapse.contracts import Change
from lapse.graph import db

pytestmark = pytest.mark.db


def test_executor_queries_claim_once_and_bind_evidence_to_account():
    g = db.graph(f"lapse:test:wp8:{uuid4().hex}")
    started = datetime.now(UTC)
    traces = []
    try:
        db.run(g, "policy_service", {"services": [{"id": "x", "name": "X"}]}, write=True)
        db.run(
            g,
            "fixture_accounts",
            {
                "accounts": [
                    {"id": "account", "service_id": "x", "display": "X"},
                    {"id": "unrelated", "service_id": "x", "display": "Other X account"},
                ]
            },
            write=True,
        )
        db.run(
            g,
            "fixture_roots_phone",
            {
                "roots": [
                    {"id": "old", "kind": "phone", "label": "Old", "last4": "4321"},
                    {"id": "new", "kind": "phone", "label": "New", "last4": "7788"},
                ]
            },
            write=True,
        )
        db.run(g, "planner_save_plan", {"props": {"id": "plan"}}, write=True)
        change = Change(
            id="change",
            plan_id="plan",
            order=1,
            account_id="account",
            account_label="X",
            role="login_phone",
            from_root="old",
            to_root="new",
            tier=2,
            requires_old_root=False,
            status="approved",
        )
        db.run(
            g,
            "planner_save_steps",
            {"plan_id": "plan", "steps": [change.model_dump(mode="json", exclude_none=True)]},
            write=True,
        )
        row = db.run(g, "exec_context", {"change_id": "change"}).rows[0]
        assert row["account"]["id"] == "account"
        assert row["new_root"]["last4"] == "7788"
        params = {"change_id": "change", "started_at": started.isoformat()}
        first = db.run(g, "exec_start", params, write=True, trace=lambda *t: traces.append(t))
        assert first.rows[0]["change"]["status"] == "running"
        assert first.rows[0]["change"]["started_at"] == started.isoformat()
        assert db.run(g, "exec_start", params, write=True).rows == []
        assert db.run(g, "exec_pending").rows == []
        for account, evidence in [("account", "matching"), ("unrelated", "unrelated")]:
            db.run(
                g,
                "fixture_evidence",
                {
                    "account_id": account,
                    "root_ids": ["new"],
                    "props": {
                        "id": evidence,
                        "date": (started + timedelta(seconds=1)).isoformat(),
                        "subject": "Your phone number changed",
                        "snippet": "Changed to ••7788",
                    },
                },
                write=True,
            )
        db.run(g, "exec_release", {"change_id": "change"}, write=True)
        pending = db.run(g, "exec_pending").rows
        assert len(pending) == 1
        assert [e["id"] for e in pending[0]["evidence"]] == ["matching"]
        assert traces[0][0] == "exec_start"
        assert traces[0][3] == 1
    finally:
        g.delete()
