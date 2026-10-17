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
        4,
    )
    assert len(plan.steps) == 7
    assert plan.exposure_before - sum(step.exposure_removed for step in plan.steps) == plan.exposure_after
    assert [step.order for step in plan.steps] == list(range(1, 8))
    assert plan.deadline == date(2026, 10, 31)
    assert all(step.due == date(2026, 10, 30) for step in plan.steps)
    assert not plan.steps[0].requires_old_root
    assert planner.get_plan("planner-test", plan.id) == plan
    assert planner.list_plans("planner-test") == [plan]
    assert planner.get_plan("planner-test", "missing") is None
    assert planner_graph.ro_query("MATCH (:Change)-[b:BEFORE]->(:Change) RETURN count(b)").result_set == [[6]]
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
        "CREATE (m:Method {id: 'observed', account_id: 'google', source: 'observed', needs_password: true}) "
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
        ["sms_2fa", "phone_new"],
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
    assert removed.remaining_accounts == ["canva", "coursera", "figma", "microsoft"]
    assert all(account in removed.note for account in removed.remaining_accounts)
    assert planner.get_plan("planner-test", removed.id) == removed


def test_empty_plan_and_invalid_roots(planner_graph):
    manual = planner.plan_for_root("planner-test", "device_phone")
    assert [(step.account_id, step.tier) for step in manual.steps] == [("github", 3)]
    planner_graph.query("CREATE (:Root:Device {id: 'unused', kind: 'device', label: 'Unused'})")
    plan = planner.plan_for_root("planner-test", "unused")
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
    done = planner.apply_change_done("planner-test", plan.steps[0].id)
    assert done.status == ChangeStatus.done
    assert done.to_root is None
    assert planner_graph.ro_query(query).result_set == [["email_college"]]
    assert planner_graph.ro_query(
        "MATCH (:Account {id: 'google'})-[:USES]->(:Root {id: 'phone_old'}) RETURN count(*)"
    ).result_set == [[0]]


@pytest.mark.parametrize("old,new", [("phone_old", "phone_new"), ("email_college", "email_primary")])
def test_scenario_plan_apply_repairs_combined_exposure(planner_graph, old, new):
    before = evaluate_scenario(planner_graph, ScenarioRequest(kind="lockout", root_ids=[old]))
    baseline = {node.node_id for node in before.baseline.reached.values() if node.node_type == "Account"}
    plan = planner.plan_for_root("planner-test", old, new)
    assert plan.exposure_before > 0
    assert plan.exposure_after == 0
    assert len({(step.account_id, step.from_root) for step in plan.steps}) == len(plan.steps)
    if old == "phone_old":
        assert (plan.takeover_before, plan.lockout_before) == (10, 4)
        assert next(step for step in plan.steps if step.account_id == "dropbox").exposure_removed > 0
    for step in plan.steps:
        planner.apply_change_done("planner-test", step.id)
    after = evaluate_scenario(planner_graph, ScenarioRequest(kind="lockout", root_ids=[old]))
    lost = baseline - after.closure.reached.keys()
    taken = set()
    if old == "phone_old":
        taken = {
            node.node_id
            for node in evaluate_scenario(
                planner_graph, ScenarioRequest(kind="takeover", root_ids=[old])
            ).result.affected_accounts
        }
    assert taken | lost == set()


def test_inactive_phone_still_measures_lost_access(planner_graph):
    planner_graph.query("MATCH (r:Root {id: 'phone_old'}) SET r.status = 'inactive'")
    plan = planner.plan_for_root("planner-test", "phone_old", "phone_new")
    assert (plan.takeover_before, plan.lockout_before, plan.exposure_before) == (10, 4, 10)
    assert plan.exposure_after == 0


def test_missing_procedure_and_unknown_accounts_are_manual_steps(planner_graph, monkeypatch):
    policies, _ = load_policy_file(ROOT_DIR / "fixtures/policy.yaml")
    next(policy for policy in policies if policy.service.id == "swiggy").change = []
    monkeypatch.setattr(planner, "_policies", lambda: policies)
    planner_graph.query(
        "MATCH (a:Account {id: 'splitwise'}), (r:Root {id: 'phone_old'}) "
        "CREATE (a)-[:USES {role: 'login_phone'}]->(r)"
    )
    plan = planner.plan_for_root("planner-test", "phone_old", "phone_new")
    steps = {step.account_id: step for step in plan.steps}
    assert steps["swiggy"].tier == 3
    assert "manual: no documented procedure" in steps["swiggy"].note
    assert steps["splitwise"].tier == 3
    assert "unknown, not safe" in steps["splitwise"].note
    assert "splitwise" in plan.unknown_accounts
    assert "splitwise" in plan.note
    assert plan.exposure_after == 0


def test_graph_copy_serializes_concurrent_callers(planner_graph):
    from concurrent.futures import ThreadPoolExecutor

    names = [f"lapse:test:copy:{uuid4().hex}" for _ in range(3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        copies = list(pool.map(lambda name: db.copy_graph(planner_graph, name), names))
    try:
        assert len(copies) == 3
        assert all(copy.ro_query("MATCH (a:Account) RETURN count(a)").result_set == [[17]] for copy in copies)
    finally:
        for copy in copies:
            copy.delete()


def test_graph_copy_retries_fork_conflicts(planner_graph, monkeypatch):
    from redis.exceptions import ResponseError

    original_copy = Graph.copy
    attempts = 0

    def copy(g, name):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ResponseError("Failed to fork for GRAPH.COPY")
        return original_copy(g, name)

    monkeypatch.setattr(Graph, "copy", copy)
    copied = db.copy_graph(planner_graph, f"lapse:test:copy:{uuid4().hex}")
    copied.delete()
    assert attempts == 3


def test_graph_copy_wait_has_a_timeout(planner_graph):
    lock = planner_graph.client.connection.lock("lapse:lock:graph-copy", timeout=5)
    with lock, pytest.raises(TimeoutError, match="waiting for GRAPH.COPY"):
        db.copy_graph(planner_graph, f"lapse:test:copy:{uuid4().hex}", timeout_s=0.01)


def test_legacy_single_role_change_keeps_other_roles(planner_graph):
    from lapse.contracts import Change

    legacy = Change(
        id="legacy",
        plan_id="legacy-plan",
        order=1,
        account_id="google",
        account_label="Google",
        role="recovery_phone",
        from_root="phone_old",
        to_root="phone_new",
        tier=3,
        requires_old_root=False,
    )
    planner._apply(planner_graph, legacy, planner._policies())
    assert planner_graph.ro_query(
        "MATCH (:Account {id: 'google'})-[u:USES]->(r) "
        "WHERE u.role IN ['recovery_phone', 'sms_2fa'] RETURN u.role, r.id ORDER BY u.role"
    ).result_set == [["recovery_phone", "phone_new"], ["sms_2fa", "phone_old"]]


@pytest.mark.parametrize("old,new", [("phone_old", "phone_new"), ("email_college", "email_primary")])
def test_full_policy_fixture_scenario_plan_apply(monkeypatch, old, new):
    g = db.graph(f"lapse:test:wave2:integration:{uuid4().hex}")
    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    _, carriers = load_policy_file(ROOT_DIR / "lapse/policy/carriers.yaml")
    load_persona(g, policies, carriers)
    monkeypatch.setattr(db, "user_graph", lambda uid: g)
    monkeypatch.setattr(planner, "_policies", lambda: policies)
    try:
        original = evaluate_scenario(g, ScenarioRequest(kind="lockout", root_ids=[old]))
        baseline = {
            node.node_id for node in original.baseline.reached.values() if node.node_type == "Account"
        }
        plan = planner.plan_for_root("integration-test", old, new)
        assert plan.exposure_after == 0
        if old == "phone_old":
            assert next(step for step in plan.steps if step.account_id == "dropbox").exposure_removed == 1
        for step in plan.steps:
            planner.apply_change_done("integration-test", step.id)
        after = evaluate_scenario(g, ScenarioRequest(kind="lockout", root_ids=[old]))
        lost = baseline - after.closure.reached.keys()
        taken = set()
        if old == "phone_old":
            taken = {
                node.node_id
                for node in evaluate_scenario(
                    g, ScenarioRequest(kind="takeover", root_ids=[old])
                ).result.affected_accounts
            }
        assert taken | lost == set()
    finally:
        g.delete()
