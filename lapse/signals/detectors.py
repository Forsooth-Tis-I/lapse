from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import httpx
import tldextract

from lapse.contracts import Root, ScenarioRequest, Signal, SignalKind
from lapse.graph import db, planner, scenarios
from lapse.policy import loader

_LOG = logging.getLogger(__name__)
_DOMAIN = tldextract.TLDExtract(suffix_list_urls=())


def _timestamp(value: str | datetime | date) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def rdap_expiry(domain: str, *, client=None) -> date | None:
    """Read the earliest RDAP expiration event, with a bounded network request."""
    if client is None:
        with httpx.Client(follow_redirects=True) as owned:
            return rdap_expiry(domain, client=owned)
    try:
        response = client.get(f"https://rdap.org/domain/{domain}", timeout=5.0)
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict) or not isinstance(document.get("events", []), list):
            return None
        dates = []
        for event in document.get("events", []):
            if not isinstance(event, dict) or event.get("eventAction") != "expiration":
                continue
            try:
                dates.append(_timestamp(event["eventDate"]).date())
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return min(dates, default=None)
    except (httpx.HTTPError, ValueError):
        return None


def _save(uid: str, signal: Signal, *, scenario_id=None, trace=None) -> Signal:
    g = db.user_graph(uid)
    params = {
        "kind": signal.kind.value,
        "root_id": signal.root_id,
        "deadline_key": signal.deadline.isoformat() if signal.deadline else "",
        "props": signal.model_dump(mode="json", exclude_none=True),
    }
    db.run(g, "signals_detector_adopt", params, write=True, trace=trace)
    row = db.run(g, "signals_detector_merge", params, write=True, trace=trace).rows[0]
    saved = Signal.model_validate(row["signal"])
    if not row["notified"] and saved.status == "open":
        _notify(uid, saved, scenario_id=scenario_id, trace=trace)
    return saved


def _notify(uid: str, signal: Signal, *, scenario_id=None, trace=None) -> None:
    try:
        from lapse.notify import notify
    except ModuleNotFoundError as exc:
        if exc.name != "lapse.notify":
            raise
        _LOG.warning("Notification module unavailable; signal delivery remains pending")
        return
    path = f"/graph?scenario={scenario_id}" if scenario_id else f"/graph?root={signal.root_id}"
    notify(
        uid,
        signal.detail,
        [
            {"label": "Show risk", "action": "open_web", "payload": {"path": path}},
            {"label": "Plan the fix", "action": "plan_root", "payload": {"root_id": signal.root_id}},
            {"label": "Not mine", "action": "dismiss_signal", "payload": {"signal_id": signal.id}},
        ],
    )
    db.run(db.user_graph(uid), "signals_detector_notified", {"id": signal.id}, write=True, trace=trace)


def run_detectors(uid: str, *, now=None, trace=None, rdap_client=None) -> list[Signal]:
    """Evaluate current evidence and persist one signal per kind, root and deadline."""
    now = _timestamp(now) if now is not None else datetime.now(UTC)
    g = db.user_graph(uid)
    for row in db.run(g, "signals_detector_pending", trace=trace).rows:
        _save(uid, Signal.model_validate(row["signal"]), trace=trace)
    rows = db.run(g, "signals_detector_roots", trace=trace).rows
    signals = []

    def emit(kind, root, title, detail, deadline=None, scenario_id=None):
        key = "\0".join((kind, root.id, deadline.isoformat() if deadline else ""))
        signal = Signal(
            id="signal:" + sha256(key.encode()).hexdigest()[:24],
            kind=kind,
            root_id=root.id,
            at=now,
            title=title,
            detail=detail,
            deadline=deadline,
        )
        saved = _save(uid, signal, scenario_id=scenario_id, trace=trace)
        if saved.id not in {item.id for item in signals}:
            signals.append(saved)

    def risk(root, kind):
        return scenarios.run_scenario(uid, ScenarioRequest(kind=kind, root_ids=[root.id]), trace=trace)

    def caveat(result):
        text = " Under the methods we model."
        if result.unknown_accounts:
            text += f" {len(result.unknown_accounts)} other accounts are unknown, not safe."
        return text

    for row in rows:
        root = Root.model_validate(row["root"])
        if root.kind == "phone" and root.status in {"retiring", "inactive"} and root.reissue_after:
            result = risk(root, "takeover")
            full = len(result.affected_accounts)
            indirect = full - len(result.direct_accounts)
            label = "••" + root.last4 if root.last4 else root.label
            emit(
                SignalKind.reissue_countdown,
                root,
                "Phone number can be reissued",
                f"{label} can be reissued to a stranger from {root.reissue_after}. "
                f"{full} accounts still use it ({indirect} through other accounts)." + caveat(result),
                root.reissue_after,
                result.id,
            )
        if root.kind == "email" and root.status == "closing" and root.closes_at:
            result = risk(root, "lockout")
            emit(
                SignalKind.closing_email,
                root,
                "Email account is closing",
                f"{root.address or root.label} closes on {root.closes_at}; "
                f"lost outright: {len(result.lost_now_accounts)} accounts; "
                f"no way back if you forget the password: {len(result.recovery_lost_accounts)} accounts."
                + caveat(result),
                root.closes_at,
                result.id,
            )
        if root.kind == "email" and root.email_kind == "custom" and root.address:
            host = root.address.rsplit("@", 1)[-1].lower()
            domain = _DOMAIN(host).top_domain_under_public_suffix or host
            expires = rdap_expiry(domain, client=rdap_client)
            if expires is not None:
                db.run(
                    g,
                    "signals_detector_expiry",
                    {"root_id": root.id, "expires_at": expires.isoformat()},
                    write=True,
                    trace=trace,
                )
                result = risk(root, "takeover")
                emit(
                    SignalKind.domain_expiry,
                    root,
                    "Email domain expires",
                    f"{domain} expires on {expires}; "
                    f"{len(result.affected_accounts)} accounts could be reached." + caveat(result),
                    expires,
                    result.id,
                )
        if root.kind == "phone":
            seen = [_timestamp(value) for value in row["seen"] if value and _timestamp(value) <= now]
            last_seen = max(seen, default=None)
            first_seen = row["root"].get("first_seen")
            inactive_recent = (
                root.status == "inactive" and last_seen and last_seen >= now - timedelta(days=30)
            )
            old = last_seen or (_timestamp(first_seen) if first_seen else None)
            active_stale = root.status == "active" and old and old <= now - timedelta(days=180)
            if inactive_recent or active_stale:
                reason = (
                    "It appears in evidence from the last 30 days despite being marked inactive."
                    if inactive_recent
                    else "It has not appeared in evidence for at least 180 days."
                )
                emit(
                    SignalKind.stale_root,
                    root,
                    "Check phone status",
                    f"Do you still have {root.label}? {reason}",
                )

    for row in db.run(g, "signals_detector_devices", {"now": now.isoformat()}, trace=trace).rows:
        root = Root.model_validate(row["root"])
        result = risk(root, "lockout")
        emit(
            SignalKind.new_device,
            root,
            "Check your authenticator",
            f"A new device was observed. Did you move your authenticator app from {root.label}? "
            f"Losing the old device would lock you out of {len(result.affected_accounts)} accounts."
            + caveat(result),
            scenario_id=result.id,
        )

    missed = db.run(g, "signals_detector_missed", {"now": now.isoformat()}, trace=trace).rows
    policies = (
        [policy for path in loader.default_policy_paths() for policy in loader.load_policy_file(path)[0]]
        if missed
        else []
    )
    handled = set()
    for row in missed:
        root = Root.model_validate(row["root"])
        if root.id in handled:
            continue
        handled.add(root.id)
        account_ids = {item["account_id"] for item in missed if item["root"]["id"] == root.id}
        services = {
            policy.service.id
            for policy in policies
            if any(procedure.root_kind == root.kind for procedure in policy.change)
        }
        plannable = {
            candidate["account_id"]
            for candidate in db.run(g, "planner_candidates", {"root_id": root.id}, trace=trace).rows
            if candidate["service_id"] in services
        }
        detail = f"New evidence still references {root.label}."
        if account_ids & plannable:
            plan = planner.plan_for_root(uid, root.id, row["new_root"], trace=trace)
            included = {step.account_id for step in plan.steps}
            count = len(account_ids & included)
            detail += f" {count} missed accounts were added to follow-up plan {plan.id}."
        else:
            included = set()
        manual = len(account_ids - included)
        if manual:
            detail += f" {manual} accounts need manual review because no modelled change is available."
        emit(
            SignalKind.missed_account,
            root,
            "Accounts found after a completed change",
            detail,
        )
    return signals
