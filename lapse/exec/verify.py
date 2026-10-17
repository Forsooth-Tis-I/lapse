import re
from datetime import UTC, datetime
from email.utils import parseaddr
from html import escape

from lapse.contracts import EventKind, Evidence, Root, UseRole
from lapse.exec.base import StepEmitter, contact_value
from lapse.exec.jobs import load_policies
from lapse.graph import db
from lapse.graph.planner import apply_change_done
from lapse.ingest.parsers import contact_change


def matches_confirmation(
    evidence: Evidence,
    *,
    started_at: datetime,
    domains: list[str],
    patterns: list[str],
    new_root: Root | None,
    role: UseRole | None = None,
) -> bool:
    date = evidence.date.replace(tzinfo=UTC) if evidence.date.tzinfo is None else evidence.date
    started_at = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    if date <= started_at or evidence.event != EventKind.contact_changed:
        return False
    domain = parseaddr(evidence.sender)[1].rpartition("@")[2].lower()
    if not any(domain == allowed or domain.endswith("." + allowed) for allowed in domains):
        return False
    text = f"{evidence.subject}\n{evidence.snippet}"
    if role is not None:
        kind = "email" if role in {UseRole.login_email, UseRole.recovery_email} else "phone"
        if re.search(r"(?i)recovery\s+(?:phone|mobile|email|e-mail)", text):
            described_role = f"recovery_{kind}"
        elif re.search(r"(?i)(?:two[- ](?:step|factor)|2fa|sms verification)", text):
            described_role = "sms_2fa"
        else:
            described_role = f"login_{kind}"
        if role != described_role:
            return False
    if not any(re.search(pattern, text) for pattern in patterns):
        return False
    if new_root is not None:
        target = new_root.address or new_root.last4 or (new_root.e164 or "")[-4:]
        if not target or target.casefold() not in text.casefold():
            return False
        parsed = contact_change(text)
        if parsed is None or parsed.kind != new_root.kind:
            return False
        replacement = parsed.new_email if new_root.kind == "email" else parsed.new_last4
        if not replacement or replacement.casefold() != target.casefold():
            return False
    return True


def verify_pending(uid: str, *, trace=None) -> list[str]:
    from lapse.notify import notify

    policies = load_policies()
    rows = db.run(db.user_graph(uid), "exec_pending", trace=trace).rows
    completed = []
    for row in rows:
        change = row["change"]
        policy = policies.get(row["account"]["service_id"])
        if policy is None:
            continue
        procedure = next((p for p in policy.change if p.root_kind == row["old_root"]["kind"]), None)
        if procedure is None:
            continue
        new_root = Root.model_validate(row["new_root"]) if row["new_root"] else None
        if change.get("to_root") and new_root is None:
            continue
        for raw in row["evidence"]:
            if not raw:
                continue
            evidence = Evidence.model_validate(raw)
            if matches_confirmation(
                evidence,
                started_at=datetime.fromisoformat(change["started_at"]),
                domains=policy.service.domains,
                patterns=procedure.confirmation_patterns,
                new_root=new_root,
                role=UseRole(change["role"]),
            ):
                apply_change_done(uid, change["id"], evidence.id, trace=trace)
                service = f"<b>{escape(policy.service.name)}</b>"
                message = (
                    f"Done ✅ {service} now uses {contact_value(new_root)}."
                    if new_root
                    else f"Done ✅ {service} no longer uses your old contact."
                )
                StepEmitter(uid, change["id"], trace=trace).emit("done", message)
                notify(uid, message)
                completed.append(change["id"])
                break
    return completed
