from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import UTC
from hashlib import sha256
from importlib import import_module
from typing import Literal

from lapse.contracts import EventKind, ExtractedEvent, Root, Service, ServicePolicy, Uses
from lapse.graph import db
from lapse.ingest.parsers import safe_text
from lapse.policy.loader import default_policy_paths, load_policy_file

_EMAIL_CONFIRMING = {EventKind.signup, EventKind.verify_email, EventKind.otp_email}
_PHONE_CONFIRMING = {EventKind.otp_sms_notice, EventKind.twofa_enabled, EventKind.contact_changed}


def _id(prefix: str, *parts: str) -> str:
    return prefix + ":" + sha256("\0".join(parts).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class _Resolution:
    root: Root
    match: Literal["known", "unknown", "ambiguous"]


def _phone_role(event: ExtractedEvent, policy: ServicePolicy | None) -> str:
    text = (event.subject + " " + event.snippet).lower()
    roles = {role for method in policy.methods for role in method.needs_roles} if policy else set()
    if re.search(r"recovery\s+(?:phone|mobile)", text):
        return "recovery_phone"
    if "login_phone" in roles:
        return "login_phone"
    if event.event in {EventKind.otp_sms_notice, EventKind.twofa_enabled} or "sms_2fa" in roles:
        return "sms_2fa"
    return "recovery_phone"


def _service(event: ExtractedEvent, policies: dict[str, ServicePolicy]) -> Service:
    if event.service_id in policies:
        return policies[event.service_id].service
    domain = re.sub(r"[^a-z0-9.-]", "", event.sender_domain.lower())
    return Service(
        id="unknown:" + domain if domain else _id("unknown", event.service_guess or event.sender),
        name=event.service_guess or domain or "Unknown service",
        domains=[domain] if domain else [],
        modelled=False,
    )


def _publish(uid: str, counts: dict, *, status: str) -> None:
    try:
        module = import_module("lapse.events")
    except ModuleNotFoundError as exc:
        if exc.name != "lapse.events":
            raise
        return
    module.publish(
        uid,
        "ingest",
        {
            "emails_scanned": counts["evidence"],
            "accounts_found": counts["accounts"],
            "edges_inferred": counts["inferred_uses"],
            "edges_confirmed": counts["confirmed_uses"],
            "status": status,
        },
    )


def _account_identity(g, event, service_id, identifier, evidence_id, order, *, trace=None):
    change = event.contact_change if event.event == EventKind.contact_changed else None
    login_change = (
        change
        and change.kind == "email"
        and change.new_email
        and not re.search(r"recovery\s+e-?mail", event.subject + " " + event.snippet, re.IGNORECASE)
    )
    old_email = change.old_email.strip().lower() if login_change and change.old_email else None
    keys = {identifier}
    if login_change:
        keys.add(change.new_email.strip().lower())
        if change.old_email:
            keys.add(change.old_email.strip().lower())
    rows = db.run(
        g,
        "ingest_account_candidates",
        {"service_id": service_id, "evidence_id": evidence_id},
        trace=trace,
    ).rows
    observed = [row for row in rows if row["observed"]]
    candidates = observed or [
        row
        for row in rows
        if keys.intersection(
            [
                row["account"].get("identifier"),
                *row["emails"],
                *row["account"].get("previous_identifiers", []),
                *(row["pending_emails"] if login_change and not old_email else []),
            ]
        )
    ]
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous account identity for service {service_id}")
    if candidates and old_email and not observed:
        candidate = candidates[0]
        if old_email not in {
            candidate["account"].get("identifier"),
            *candidate["emails"],
            *candidate["account"].get("previous_identifiers", []),
        }:
            candidates = []
    if login_change and rows and not candidates:
        raise ValueError(f"Unresolved account identity for email change on service {service_id}")
    account = candidates[0]["account"] if candidates else {}
    result = {
        "id": account.get("id", _id("account", service_id, identifier)),
        "identifier": account.get("identifier") or identifier,
    }
    if login_change:
        previous = set(account.get("previous_identifiers", []))
        previous.add(result["identifier"])
        previous.add(change.new_email.strip().lower())
        if change.old_email:
            previous.add(change.old_email.strip().lower())
        if order >= account.get("identifier_order", ""):
            result.update(identifier=change.new_email.strip().lower(), identifier_order=order)
        previous.discard(result["identifier"])
        result["previous_identifiers"] = sorted(previous)
    return result


def write_events(uid: str, events: list[ExtractedEvent], *, trace=None) -> dict:
    """Merge observations and return aggregate counts for the user's graph."""
    g = db.user_graph(uid)
    db.ensure_schema(g)
    policies = [policy for path in default_policy_paths() for policy in load_policy_file(path)[0]]
    by_service = {policy.service.id: policy for policy in policies}
    roots = {
        row["root"]["id"]: Root.model_validate(row["root"])
        for row in db.run(g, "ingest_roots", trace=trace).rows
    }
    touched = set()

    def save_root(root: Root) -> Root:
        db.run(
            g,
            f"ingest_root_{root.kind}",
            {"props": root.model_dump(mode="json", exclude_none=True)},
            write=True,
            trace=trace,
        )
        roots[root.id] = root
        return root

    def phone(suffix: str) -> _Resolution:
        matches = [
            r
            for r in roots.values()
            if r.kind == "phone"
            and r.confirmed
            and r.last4
            and len(r.last4) == 4
            and r.last4.endswith(suffix)
        ]
        if len(matches) == 1:
            return _Resolution(matches[0], "known")
        root_id = _id("phone:unknown", suffix)
        root = roots.get(root_id) or save_root(
            Root(
                id=root_id,
                kind="phone",
                label="••" + suffix,
                last4=suffix,
                status="unknown",
                confirmed=False,
            )
        )
        return _Resolution(root, "ambiguous" if matches else "unknown")

    def email(address: str) -> _Resolution:
        address = address.strip().lower()
        matches = [
            r for r in roots.values() if r.kind == "email" and r.address and r.address.lower() == address
        ]
        if len(matches) == 1:
            root = matches[0]
            return _Resolution(root, "known" if root.confirmed else "unknown")
        root = save_root(
            Root(
                id=_id("email:unknown", address),
                kind="email",
                address=address,
                label=address,
                status="unknown",
                confirmed=False,
            )
        )
        return _Resolution(root, "ambiguous" if matches else "unknown")

    def write_event(event: ExtractedEvent) -> None:
        inbox = roots.get(event.inbox)
        if inbox is None and event.account_identifier and "@" in event.account_identifier:
            inbox = save_root(
                Root(
                    id=event.inbox,
                    kind="email",
                    address=event.account_identifier.strip().lower(),
                    label=event.account_identifier.strip().lower(),
                    status="unknown",
                    confirmed=False,
                )
            )
        identifier = event.account_identifier or (inbox.address if inbox else None)
        if not identifier:
            raise ValueError("An account identifier or an inbox root address is required")
        identifier = identifier.strip().lower()
        service = _service(event, by_service)
        policy = by_service.get(service.id)
        evidence_id = _id("evidence", event.inbox, event.msg_id)
        at = event.date.astimezone(UTC).isoformat()
        order = at + "|" + event.msg_id + "|" + event.inbox
        identity = _account_identity(g, event, service.id, identifier, evidence_id, order, trace=trace)
        account_id = identity["id"]
        evidence = {
            "id": evidence_id,
            "msg_id": event.msg_id,
            "inbox": event.inbox,
            "date": at,
            "sender": event.sender,
            "subject": safe_text(event.subject, context=event.snippet),
            "snippet": safe_text(event.snippet, context=event.subject)[:300],
            "event": event.event.value,
            "observed_order": order,
        }
        db.run(
            g,
            "ingest_account",
            {
                "service": service.model_dump(mode="json", exclude_none=True),
                "account": {
                    **identity,
                    "service_id": service.id,
                    "display": service.name,
                    "modelled": service.modelled,
                },
                "evidence": evidence,
                "at": at,
            },
            write=True,
            trace=trace,
        )
        touched.add(account_id)
        mentions = set()
        if inbox is not None and inbox.kind == "email":
            mentions.add(inbox.id)

        def use(resolution: _Resolution, role: str, decisive: bool, *, repoint: bool = False) -> None:
            mentions.add(resolution.root.id)
            confirmed = decisive and resolution.match == "known"
            props = Uses(
                account_id=account_id,
                root_id=resolution.root.id,
                role=role,
                confirmed=confirmed,
                confidence=max(0.0, min(1.0, event.confidence)),
                evidence_ids=[evidence_id],
            ).model_dump(mode="json")
            if repoint and resolution.match != "ambiguous":
                db.run(
                    g,
                    "ingest_repoint",
                    {
                        **props,
                        "evidence_id": evidence_id,
                        "order": order,
                    },
                    write=True,
                    trace=trace,
                )
            db.run(g, "ingest_use", {**props, "order": order}, write=True, trace=trace)

        def signal(kind: str, root: Root | None, title: str, deadline=None) -> None:
            props = {
                "id": _id("signal", evidence_id, kind, root.id if root else ""),
                "kind": kind,
                "at": at,
                "title": title,
                "detail": service.id,
            }
            if root:
                props["root_id"] = root.id
            if deadline:
                props["deadline"] = deadline.isoformat()
            db.run(g, "ingest_signal", {"props": props}, write=True, trace=trace)

        change = event.contact_change if event.event == EventKind.contact_changed else None
        changing_login_email = change and change.kind == "email" and change.new_email
        if inbox is not None and inbox.kind == "email" and not changing_login_email:
            use(_Resolution(inbox, "known"), "login_email", event.event in _EMAIL_CONFIRMING)

        role = _phone_role(event, policy)
        phones = {
            suffix: phone(suffix) for suffix in event.phone_last4 if re.fullmatch(r"\d{2}|\d{4}", suffix)
        }
        mentions.update(res.root.id for res in phones.values())
        if change and change.kind in {"phone", "email"}:
            if change.kind == "phone":
                old_value, new_value, resolve = change.old_last4, change.new_last4, phone
            else:
                old_value, new_value, resolve = change.old_email, change.new_email, email
                role = (
                    "recovery_email"
                    if "recovery email" in (event.subject + " " + event.snippet).lower()
                    else "login_email"
                )
            old = resolve(old_value) if old_value else None
            new = resolve(new_value) if new_value else None
            if new and not old and new.match != "ambiguous":
                previous = db.run(
                    g,
                    "ingest_role_roots",
                    {"account_id": account_id, "role": role, "order": order},
                    trace=trace,
                ).rows
                for row in previous:
                    root = roots[row["root_id"]]
                    mentions.add(root.id)
                    if root.status in {"retiring", "unknown"}:
                        signal("policy_event", root, "Contact changed on a watched root")
            for resolution in (old, new):
                if resolution:
                    mentions.add(resolution.root.id)
                    if resolution.root.status in {"retiring", "unknown"}:
                        signal("policy_event", resolution.root, "Contact changed on a watched root")
            if new:
                use(new, role, True, repoint=True)
        else:
            for resolution in phones.values():
                use(resolution, role, event.event in _PHONE_CONFIRMING)

        for address in event.emails_mentioned:
            mentions.add(email(address).root.id)
        if (
            event.event == EventKind.deactivation_notice
            and event.deadline
            and inbox
            and inbox.kind == "email"
        ):
            db.run(
                g,
                "ingest_closing_email",
                {"root_id": inbox.id, "deadline": event.deadline.isoformat(), "order": order},
                write=True,
                trace=trace,
            )
            roots[inbox.id] = inbox.model_copy(update={"status": "closing", "closes_at": event.deadline})
            signal("closing_email", inbox, "Mailbox closure announced", event.deadline)
        if event.event == EventKind.new_device:
            device = None
            if event.device:
                device = next(
                    (r for r in roots.values() if r.kind == "device" and r.name == event.device), None
                )
                device = device or save_root(
                    Root(
                        id=_id("device:unknown", event.device),
                        kind="device",
                        label=event.device,
                        name=event.device,
                        status="unknown",
                        confirmed=False,
                    )
                )
                mentions.add(device.id)
            signal("new_device", device, "New device observed")
        db.run(
            g,
            "ingest_mentions",
            {"evidence_id": evidence_id, "root_ids": sorted(mentions)},
            write=True,
            trace=trace,
        )

    for event in sorted(events, key=lambda e: (e.date, e.msg_id, e.inbox)):
        write_event(event)

    if touched:
        compile_user_graph = import_module("lapse.policy.compile").compile_user_graph
        parameters = inspect.signature(compile_user_graph).parameters
        kwargs = {"account_ids": sorted(touched)} if "account_ids" in parameters else {}
        if "trace" in parameters:
            kwargs["trace"] = trace
        compile_user_graph(g, policies, **kwargs)
    counts = db.run(g, "ingest_summary", trace=trace).rows[0]
    counts["per_service"] = {
        row["service_id"]: row["accounts"] for row in db.run(g, "ingest_service_counts", trace=trace).rows
    }
    _publish(uid, counts, status="running" if events else "done")
    return counts
