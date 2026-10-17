from collections import defaultdict
from itertools import product

from falkordb.graph import Graph

from lapse.contracts import CarrierRule, ServicePolicy
from lapse.graph.db import ensure_schema, policy_graph, run


def write_policy_graph(
    policies: list[ServicePolicy], carriers: list[CarrierRule], *, g: Graph | None = None
) -> None:
    if g is None:
        g = policy_graph()
    services, methods, changes = [], [], []
    for policy in policies:
        service_id = policy.service.id
        services.append(
            {
                **policy.service.model_dump(mode="json", exclude_none=True),
                "verified_at": policy.verified_at.isoformat() if policy.verified_at else None,
            }
        )
        for template in policy.methods:
            methods.append(
                {
                    **template.model_dump(mode="json", exclude_none=True),
                    "id": f"{service_id}:{template.id}",
                    "template_id": template.id,
                    "service_id": service_id,
                }
            )
        for index, change in enumerate(policy.change):
            changes.append(
                {
                    **change.model_dump(mode="json", exclude_none=True),
                    "id": f"{service_id}:{change.root_kind}:{index}",
                    "service_id": service_id,
                }
            )
    run(g, "policy_clear", write=True)
    ensure_schema(g)
    run(g, "policy_service", {"services": services}, write=True)
    run(g, "policy_methods", {"methods": methods}, write=True)
    run(g, "policy_changes", {"changes": changes}, write=True)
    run(g, "policy_carriers", {"carriers": [c.model_dump(mode="json") for c in carriers]}, write=True)


def compile_user_graph(
    g: Graph, policies: list[ServicePolicy], account_ids: list[str] | None = None, *, trace=None
) -> None:
    if account_ids == []:
        return
    scope = {"all_accounts": account_ids is None, "account_ids": account_ids or []}
    by_service = {policy.service.id: policy for policy in policies}
    methods, needs = [], []
    for row in run(g, "compile_accounts", scope, trace=trace).rows:
        account = row["account"]
        policy = by_service.get(account["service_id"])
        if policy is None or not policy.service.modelled or not account.get("modelled", True):
            continue
        roles = defaultdict(set)
        for use in row["uses"]:
            if use["root_id"] is not None:
                roles[use["role"]].add(use["root_id"])
        for template in policy.methods:
            if any(roles[role] for role in template.requires_absent_roles):
                continue
            if not template.needs_roles and not template.needs_password:
                raise ValueError(f"Zero-need method {template.id} must need a password")
            choices = [sorted(roles[role]) for role in template.needs_roles]
            for index, roots in enumerate(product(*choices)):
                method_id = f"m:{account['id']}:{template.id}" + (f":{index}" if index else "")
                props = {
                    "id": method_id,
                    "account_id": account["id"],
                    "kind": template.kind,
                    "label": template.label,
                    "needs_password": template.needs_password,
                    "source": "policy",
                    "doc_url": template.doc_url,
                }
                methods.append({"props": props, "target_id": account["id"]})
                needs.extend(
                    {"method_id": method_id, "node_id": root, "role": role.value}
                    for role, root in zip(template.needs_roles, roots, strict=True)
                )
    for row in run(g, "compile_mailboxes", scope, trace=trace).rows:
        method_id = f"m:mailbox:{row['email_id']}"
        methods.append(
            {
                "props": {
                    "id": method_id,
                    "account_id": row["account_id"],
                    "kind": "mailbox",
                    "label": "Open the hosted mailbox",
                    "needs_password": False,
                    "source": "policy",
                },
                "target_id": row["email_id"],
            }
        )
        needs.append({"method_id": method_id, "node_id": row["account_id"], "role": "mailbox_account"})
    targets = set(account_ids or [])
    if account_ids is not None:
        targets.update(row["target_id"] for row in run(g, "compile_targets", scope, trace=trace).rows)
        targets.update(method["target_id"] for method in methods)
    target_scope = {"all_accounts": account_ids is None, "target_ids": sorted(targets)}
    run(g, "compile_clear_methods", scope, write=True, trace=trace)
    run(g, "compile_clear_enables", target_scope, write=True, trace=trace)
    run(g, "compile_methods", {"methods": methods}, write=True, trace=trace)
    run(g, "compile_needs", {"needs": needs}, write=True, trace=trace)
    run(g, "compile_enables", target_scope, write=True, trace=trace)
