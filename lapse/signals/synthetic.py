from __future__ import annotations

import re

from lapse.config import ROOT_DIR
from lapse.graph import db
from lapse.policy.compile import compile_user_graph
from lapse.policy.loader import load_policy_file
from lapse.signals.tenants import tenant_uids


def _validate_prefix(prefix: str) -> None:
    if not re.fullmatch(r"(?:synth_|test_)[A-Za-z0-9_]*", prefix):
        raise ValueError("Synthetic tenant prefix must start with synth_ or test_ and use letters, digits, _")


def _is_synthetic(g, *, trace=None) -> bool:
    rows = db.run(g, "signals_synth_owner", trace=trace).rows
    return len(rows) == 1 and rows[0]["synthetic"] is True


def create_synthetic_tenants(n: int, *, prefix: str = "synth_", trace=None) -> list[str]:
    _validate_prefix(prefix)
    if n < 0:
        raise ValueError("Tenant count must be nonnegative")
    uids = [f"{prefix}{i}" for i in range(n)]
    existing = set(tenant_uids())
    for uid in uids:
        g = db.user_graph(uid)
        if uid in existing and not _is_synthetic(g, trace=trace):
            raise ValueError(f"Refusing to replace non-synthetic graph {g.name}")
    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    services = {policy.service.id: policy.service for policy in policies}
    for i, uid in enumerate(uids):
        g = db.user_graph(uid)
        if uid in existing:
            g.delete()
        db.ensure_schema(g)
        db.run(
            g,
            "fixture_user",
            {"props": {"uid": uid, "name": "Synthetic demo tenant", "synthetic": True}},
            write=True,
            trace=trace,
        )
        root_groups = {
            "phone": [
                {
                    "id": "phone_old",
                    "kind": "phone",
                    "label": "Synthetic ••4321",
                    "last4": "4321",
                    "status": "retiring",
                    "reissue_after": "2027-01-29",
                },
                {
                    "id": "phone_new",
                    "kind": "phone",
                    "label": "Synthetic ••7788",
                    "last4": "7788",
                    "status": "active",
                },
            ],
            "email": [
                {
                    "id": "email_primary",
                    "kind": "email",
                    "label": f"{uid}@example.com",
                    "address": f"{uid}@example.com",
                    "hosted_by_service": "google",
                    "status": "active",
                },
                {
                    "id": "email_college",
                    "kind": "email",
                    "label": f"{uid}@example.edu",
                    "address": f"{uid}@example.edu",
                    "hosted_by_service": "college_workspace",
                    "status": "closing",
                    "closes_at": "2026-11-15",
                },
            ],
            "device": [
                {
                    "id": "device_phone",
                    "kind": "device",
                    "label": "Synthetic authenticator",
                    "status": "active",
                }
            ],
        }
        for kind, roots in root_groups.items():
            db.run(g, f"fixture_roots_{kind}", {"roots": roots}, write=True, trace=trace)
        service_ids = ["google", "college_workspace", "figma" if i % 2 else "notion", "swiggy"]
        if i % 5 != 2:
            service_ids.append("x")
        accounts = [
            {
                "id": sid,
                "service_id": sid,
                "display": services[sid].name,
                "identifier": f"{uid}@example.{'edu' if sid in ('college_workspace', 'figma', 'notion') else 'com'}",
                "status": "active",
                "modelled": True,
                "x_blue_subscriber": sid == "x" and i % 5 == 4,
            }
            for sid in service_ids
        ]
        db.run(
            g,
            "policy_service",
            {"services": [services[sid].model_dump(mode="json", exclude_none=True) for sid in service_ids]},
            write=True,
            trace=trace,
        )
        db.run(g, "fixture_accounts", {"accounts": accounts}, write=True, trace=trace)
        use_tuples = [
            ("google", "email_primary", "login_email"),
            ("google", "phone_old" if i % 2 else "phone_new", "recovery_phone"),
            ("college_workspace", "email_college", "login_email"),
            ("figma" if i % 2 else "notion", "email_college", "login_email"),
            ("swiggy", "phone_old" if i % 3 else "phone_new", "login_phone"),
        ]
        if "x" in service_ids:
            use_tuples.extend([("x", "phone_old", "login_phone"), ("x", "email_primary", "login_email")])
            if i % 5 != 1:
                use_tuples.append(("x", "phone_new" if i % 5 == 3 else "phone_old", "sms_2fa"))
            if i % 5 == 3:
                use_tuples.append(("x", "device_phone", "totp_device"))
        uses = [
            {
                "account_id": account_id,
                "root_id": root_id,
                "role": role,
                "confirmed": True,
                "confidence": 1.0,
                "evidence_ids": [],
            }
            for account_id, root_id, role in use_tuples
        ]
        db.run(g, "fixture_uses", {"uses": uses}, write=True, trace=trace)
        compile_user_graph(g, policies)
    return uids


def drop_synthetic_tenants(*, prefix: str = "synth_", trace=None) -> int:
    _validate_prefix(prefix)
    pattern = re.compile(rf"{re.escape(prefix)}[0-9]+")
    removed = 0
    for uid in tenant_uids():
        if pattern.fullmatch(uid):
            g = db.user_graph(uid)
            if _is_synthetic(g, trace=trace):
                g.delete()
                removed += 1
    return removed
