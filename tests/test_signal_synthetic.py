from uuid import uuid4

import pytest

from lapse.config import ROOT_DIR
from lapse.contracts import ScenarioRequest, UseRole
from lapse.graph import db
from lapse.graph.scenarios import evaluate_scenario
from lapse.policy.compile import compile_user_graph
from lapse.policy.loader import load_policy_file
from lapse.signals.synthetic import create_synthetic_tenants, drop_synthetic_tenants


@pytest.fixture
def synthetic_prefix():
    prefix = f"synth_test_{uuid4().hex}_"
    yield prefix
    drop_synthetic_tenants(prefix=prefix)


@pytest.mark.db
def test_synthetic_variants_change_only_sms_without_alternative_or_subscription(synthetic_prefix):
    uids = create_synthetic_tenants(20, prefix=synthetic_prefix)
    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    after_policy = [
        policy.model_copy(
            update={"methods": [m for m in policy.methods if UseRole.sms_2fa not in m.needs_roles]}
        )
        if policy.service.id == "x"
        else policy
        for policy in policies
    ]

    def outcomes(g):
        values = []
        for root in ["phone_old", "email_college"]:
            for kind in ["takeover", "lockout"]:
                evaluation = evaluate_scenario(g, ScenarioRequest(kind=kind, root_ids=[root]))
                values.append(
                    (
                        sorted(node.node_id for node in evaluation.result.affected_accounts),
                        sorted(evaluation.closure.reached),
                        sorted(evaluation.baseline.reached) if evaluation.baseline else [],
                    )
                )
        return values

    changed = []
    for i, uid in enumerate(uids):
        g = db.user_graph(uid)
        assert db.run(g, "signals_synth_owner").rows == [{"synthetic": True}]
        college = evaluate_scenario(g, ScenarioRequest(kind="lockout", root_ids=["email_college"]))
        assert "email_college" in college.baseline.reached
        assert "email_college" not in college.closure.reached
        before = outcomes(g)
        if i % 5 != 4:
            compile_user_graph(g, after_policy, account_ids=["x"])
        if outcomes(g) != before:
            changed.append(i)
    assert changed == [0, 5, 10, 15]
    assert drop_synthetic_tenants(prefix=synthetic_prefix) == 20
    assert drop_synthetic_tenants(prefix=synthetic_prefix) == 0


@pytest.mark.db
def test_synthetic_recreation_and_drop_preserve_unlabelled_graph(synthetic_prefix):
    uid = create_synthetic_tenants(1, prefix=synthetic_prefix)[0]
    g = db.user_graph(uid)
    before = db.run(g, "graph_node_count").rows
    assert create_synthetic_tenants(1, prefix=synthetic_prefix) == [uid]
    assert db.run(g, "graph_node_count").rows == before
    g.query("MATCH (u:User) SET u.synthetic = false")
    try:
        with pytest.raises(ValueError, match="Refusing to replace"):
            create_synthetic_tenants(1, prefix=synthetic_prefix)
        assert drop_synthetic_tenants(prefix=synthetic_prefix) == 0
        assert db.run(g, "graph_node_count").rows == before
    finally:
        g.delete()


@pytest.mark.parametrize("prefix", ["", "demo", "synth_*", "synth_:other"])
def test_invalid_synthetic_prefix_is_rejected_before_database_access(prefix):
    with pytest.raises(ValueError, match="prefix"):
        create_synthetic_tenants(1, prefix=prefix)
    with pytest.raises(ValueError, match="prefix"):
        drop_synthetic_tenants(prefix=prefix)


def test_negative_count_is_rejected_before_database_access():
    with pytest.raises(ValueError, match="nonnegative"):
        create_synthetic_tenants(-1)
