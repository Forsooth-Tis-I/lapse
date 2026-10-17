from datetime import date, timedelta
from uuid import uuid4

import pytest
from falkordb.graph import Graph

from lapse.config import ROOT_DIR
from lapse.contracts import ChangeStatus, MethodTemplate, ScenarioRequest
from lapse.graph import db, planner
from lapse.graph.scenarios import evaluate_scenario
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

pytestmark = pytest.mark.db


@pytest.fixture
def planner_graph(monkeypatch):
    g = db.graph(f"lapse:test:wp1:planner:{uuid4().hex}")
    policies, carriers = load_policy_file(ROOT_DIR / "fixtures/policy.yaml")
    load_persona(g, policies, carriers)
    monkeypatch.setattr(db, "user_graph", lambda uid: g)
    monkeypatch.setattr(planner.loader, "default_policy_paths", lambda: [ROOT_DIR / "fixtures/policy.yaml"])
    try:
        yield g
    finally:
        g.delete()


def test_takeover_orders_hub_first_and_persists_every_step(planner_graph, monkeypatch):
    copies = []
    original_copy = Graph.copy

    def copy(g, name):
        result = original_copy(g, name)
        copies.append(result)
        return result

    monkeypatch.setattr(Graph, "copy", copy)
    records = []
    plan = planner.plan_for_root(
        "planner-test", "phone_old", "phone_new", trace=lambda *row: records.append(row)
    )
    assert (plan.exposure_before, plan.exposure_after) == (10, 0)
    assert (plan.steps[0].account_id, plan.steps[0].role, plan.steps[0].exposure_removed) == (
        "google",
        "recovery_phone",
        6,
    )
    assert len(plan.steps) == 8
    assert plan.exposure_before - sum(step.exposure_removed for step in plan.steps) == plan.exposure_after
    assert [step.order for step in plan.steps] == list(range(1, 9))
    assert plan.deadline == date(2026, 10, 31)
    assert all(step.due == date(2026, 10, 30) for step in plan.steps)
    assert not plan.steps[0].requires_old_root
    assert planner.get_plan("planner-test", plan.id) == plan
    assert planner.list_plans("planner-test") == [plan]
    assert planner.get_plan("planner-test", "missing") is None
    assert planner_graph.ro_query("MATCH (:Change)-[b:BEFORE]->(:Change) RETURN count(b)").result_set == [[7]]
    assert copies and all(graph.name.startswith("lapse:sandbox:planner-test:") for graph in copies)
    assert all(not graph.client.connection.exists(graph.name) for graph in copies)
    assert any(row[0] == "planner_repoint_use" for row in records)
    assert any(row[0] == "closure_round" for row in records)
    assert (
        len(
            evaluate_scenario(
                planner_graph, ScenarioRequest(kind="takeover", root_ids=["phone_old"])
            ).result.affected_accounts
        )
        == 10
    )


def test_required_old_root_due_feasibility_and_tie_break(planner_graph, monkeypatch):
    policies, _ = load_policy_file(ROOT_DIR / "fixtures/policy.yaml")
    next(p for p in policies if p.service.id == "x").change[0].requires.append("old_otp")
    monkeypatch.setattr(planner, "_policies", lambda: policies)
    deadline = date.today() + timedelta(days=10)
    plan = planner.plan_for_root("planner-test", "phone_old", "phone_new", deadline)
    assert plan.feasible
    assert plan.steps[1].account_id == "x"
    required = [step for step in plan.steps if step.requires_old_root]
    assert len(required) == 1
    assert required[0].due == deadline - timedelta(days=1)
    planner_graph.query("MATCH (r:Root {id: 'phone_old'}) SET r.status = 'inactive'")
    assert not planner.plan_for_root("planner-test", "phone_old", "phone_new", deadline).feasible
    planner_graph.query("MATCH (r:Root {id: 'phone_old'}) SET r.status = 'retiring'")
    assert not planner.plan_for_root(
        "planner-test", "phone_old", "phone_new", date.today() - timedelta(days=1)
    ).feasible


def test_apply_recompiles_only_changed_account_and_is_idempotent(planner_graph):
    plan = planner.plan_for_root("planner-test", "phone_old", "phone_new")
    first = plan.steps[0]
    planner_graph.query(
        "MATCH (a:Account {id: 'google'}), (r:Root {id: 'phone_new'}) "
        "CREATE (m:Method {id: 'observed', source: 'observed', needs_password: true}) "
        "CREATE (m)-[:GRANTS]->(a), (m)-[:NEEDS]->(r)"
    )
    unaffected_query = (
        "MATCH (m:Method)-[:GRANTS]->(a:Account) WHERE a.id <> 'google' RETURN id(m), m.id ORDER BY m.id"
    )
    before = planner_graph.ro_query(unaffected_query).result_set
    updated = planner.update_change("planner-test", first.id, status=ChangeStatus.approved, note="Reviewed")
    assert updated.status == ChangeStatus.approved
    assert updated.note == "Reviewed"
    done = planner.apply_change_done("planner-test", first.id, evidence_id="evidence_1")
    assert done.status == ChangeStatus.done
    assert done.note == "Reviewed"
    assert planner_graph.ro_query(unaffected_query).result_set == before
    assert planner_graph.ro_query("MATCH (m:Method {id: 'observed'}) RETURN count(m)").result_set == [[1]]
    assert planner_graph.ro_query(
        "MATCH (:Account {id: 'google'})-[u:USES]->(r) RETURN u.role, r.id ORDER BY u.role"
    ).result_set == [
        ["recovery_email", "email_college"],
        ["recovery_phone", "phone_new"],
        ["sms_2fa", "phone_old"],
    ]
    assert planner_graph.ro_query(
        "MATCH (:Method {id: 'm:google:reset_recovery_phone'})-[:NEEDS]->(r) RETURN r.id"
    ).result_set == [["phone_new"]]
    assert (
        len(
            evaluate_scenario(
                planner_graph, ScenarioRequest(kind="takeover", root_ids=["phone_old"])
            ).result.affected_accounts
        )
        == 4
    )
    assert planner.apply_change_done("planner-test", first.id) == done
    assert planner.get_plan("planner-test", plan.id).steps[0] == done


def test_lockout_replacement_repairs_access_but_deletion_does_not(planner_graph):
    replaced = planner.plan_for_root("planner-test", "email_college", "email_primary")
    assert replaced.kind == "lockout"
    assert (replaced.exposure_before, replaced.exposure_after) == (4, 0)
    assert sum(step.exposure_removed for step in replaced.steps) == 4
    removed = planner.plan_for_root("planner-test", "email_college")
    assert (removed.exposure_before, removed.exposure_after) == (4, 4)
    assert all(step.exposure_removed == 0 for step in removed.steps)
    assert planner.get_plan("planner-test", removed.id) == removed


def test_empty_plan_and_invalid_roots(planner_graph):
    plan = planner.plan_for_root("planner-test", "device_phone")
    assert plan.steps == []
    assert planner.get_plan("planner-test", plan.id) == plan
    with pytest.raises(ValueError, match="Unknown root"):
        planner.plan_for_root("planner-test", "missing")
    with pytest.raises(ValueError, match="Unknown replacement"):
        planner.plan_for_root("planner-test", "phone_old", "missing")
    for replacement in ("phone_old", "email_primary"):
        with pytest.raises(ValueError, match="different root of the same kind"):
            planner.plan_for_root("planner-test", "phone_old", replacement)
    with pytest.raises(ValueError, match="Unknown change"):
        planner.apply_change_done("planner-test", "missing")
    with pytest.raises(ValueError, match="Unknown change"):
        planner.update_change("planner-test", "missing", status=ChangeStatus.done)


def test_sandboxes_are_deleted_if_evaluation_fails(planner_graph, monkeypatch):
    copies = []
    original_copy = Graph.copy

    def copy(g, name):
        result = original_copy(g, name)
        copies.append(result)
        return result

    def fail(*args, **kwargs):
        raise RuntimeError("test evaluator failure")

    monkeypatch.setattr(Graph, "copy", copy)
    monkeypatch.setattr(planner, "_apply", fail)
    with pytest.raises(RuntimeError, match="test evaluator failure"):
        planner.plan_for_root("planner-test", "phone_old", "phone_new")
    assert len(copies) == 2
    assert all(not graph.client.connection.exists(graph.name) for graph in copies)
    assert planner.list_plans("planner-test") == []


def test_removal_recompiles_absent_role_templates(planner_graph, monkeypatch):
    policies, _ = load_policy_file(ROOT_DIR / "fixtures/policy.yaml")
    google = next(policy for policy in policies if policy.service.id == "google")
    google.methods.append(
        MethodTemplate(
            id="without_sms",
            kind="recover",
            label="Recover without SMS",
            needs_roles=["recovery_email"],
            requires_absent_roles=["sms_2fa"],
        )
    )
    monkeypatch.setattr(planner, "_policies", lambda: policies)
    plan = planner.plan_for_root("planner-test", "phone_old")
    planner.apply_change_done("planner-test", plan.steps[0].id)
    query = "MATCH (m:Method {id: 'm:google:without_sms'})-[:NEEDS]->(r) RETURN r.id"
    assert planner_graph.ro_query(query).result_set == []
    remove_sms = next(step for step in plan.steps if step.account_id == "google" and step.role == "sms_2fa")
    done = planner.apply_change_done("planner-test", remove_sms.id)
    assert done.status == ChangeStatus.done
    assert done.to_root is None
    assert planner_graph.ro_query(query).result_set == [["email_college"]]
    assert planner_graph.ro_query(
        "MATCH (:Account {id: 'google'})-[:USES]->(:Root {id: 'phone_old'}) RETURN count(*)"
    ).result_set == [[0]]
