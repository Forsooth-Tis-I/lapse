"""Shared data contracts. Every package (graph, policy, ingest, agent, api, bot, exec, signals, web) uses these.

Change them only in the foundation branch, and update docs/api.md and docs/tools.md in the same commit.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

POLICY_GRAPH = "lapse:policy"


def user_graph_name(uid: str) -> str:
    """Each user gets an isolated FalkorDB graph (multigraph tenancy)."""
    return f"lapse:u:{uid}"


# ---------------------------------------------------------------- roots
class RootKind(StrEnum):
    phone = "phone"
    email = "email"
    domain = "domain"
    device = "device"


class RootStatus(StrEnum):
    active = "active"
    retiring = "retiring"  # still held, will be given up on drop_at / closes_at / expires_at
    inactive = "inactive"  # no longer held by the user
    closing = "closing"  # email: closure announced
    closed = "closed"
    expired = "expired"  # domain
    sold = "sold"  # device
    lost = "lost"  # device
    unknown = "unknown"


HELD_STATUSES = {RootStatus.active, RootStatus.retiring, RootStatus.closing}


class Root(BaseModel):
    id: str
    kind: RootKind
    label: str  # display text: "••4321 (Vi)", "you@gmail.com"
    status: RootStatus = RootStatus.active
    confirmed: bool = True
    # phone
    last4: str | None = None
    e164: str | None = None
    country: str | None = None
    carrier: str | None = None
    drop_at: date | None = None
    inactive_since: date | None = None
    reissue_after: date | None = None  # computed from carrier rule
    # email
    address: str | None = None
    email_kind: Literal["personal", "edu", "work", "custom"] | None = None
    hosted_by_service: str | None = None  # service id of the mailbox host, e.g. "google"
    closes_at: date | None = None
    # domain
    name: str | None = None
    registrar: str | None = None
    expires_at: date | None = None
    # device
    device_kind: Literal["phone", "laptop", "key"] | None = None


# ---------------------------------------------------------------- services, accounts, uses
class UseRole(StrEnum):
    login_email = "login_email"
    recovery_email = "recovery_email"
    login_phone = "login_phone"
    recovery_phone = "recovery_phone"
    sms_2fa = "sms_2fa"
    totp_device = "totp_device"


class Service(BaseModel):
    id: str
    name: str
    domains: list[str] = Field(default_factory=list)
    category: str | None = None
    modelled: bool = True  # False: we know the account exists but not how it recovers -> "unknown, not safe"
    doc_url: str | None = None


class Account(BaseModel):
    id: str
    service_id: str
    display: str
    identifier: str | None = None
    status: Literal["active", "closed"] = "active"
    modelled: bool = True
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class Uses(BaseModel):
    """(Account)-[:USES {role}]->(Root): the account depends on this root in this role."""

    account_id: str
    root_id: str
    role: UseRole
    confirmed: bool = False
    confidence: float = 0.5
    evidence_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- policy
class MethodTemplate(BaseModel):
    """One way to gain control of an account of this service. AND within needs_roles; OR across templates."""

    id: str  # unique within the service, e.g. "reset_recovery_phone"
    kind: Literal["login", "reset", "recover"]
    label: str
    needs_roles: list[UseRole]  # every role must be controlled (AND)
    needs_password: bool = False  # only actors who know the password can use it
    # The template applies to an account only if the account has NONE of these roles.
    # e.g. "reset by email alone" requires_absent_roles=[sms_2fa, totp_device]; the 2FA variants need them instead.
    requires_absent_roles: list[UseRole] = []
    doc_url: str | None = None


class ChangeProcedure(BaseModel):
    """How to repoint an account from one root to another."""

    root_kind: RootKind
    tier: Literal[1, 2, 3, 4]  # 1 automatic, 2 agent browser + OTP relay, 3 assisted deep link, 4 offline
    requires: list[Literal["password", "old_otp", "new_otp", "email_otp_old", "email_otp_new", "in_person"]] = []
    settings_url: str | None = None
    recipe: str | None = None  # executor recipe name for tier 1/2
    confirmation_patterns: list[str] = []  # regexes matched against evidence subject/snippet
    doc_url: str | None = None


class ServicePolicy(BaseModel):
    service: Service
    methods: list[MethodTemplate] = []
    change: list[ChangeProcedure] = []
    verified_at: date | None = None


class CarrierRule(BaseModel):
    id: str
    name: str
    country: str
    reissue_after_days: int
    source_url: str


# ---------------------------------------------------------------- evidence (ingestion output)
class EventKind(StrEnum):
    signup = "signup"
    verify_email = "verify_email"
    otp_sms_notice = "otp_sms_notice"
    otp_email = "otp_email"
    login_alert = "login_alert"
    new_device = "new_device"
    twofa_enabled = "twofa_enabled"
    twofa_disabled = "twofa_disabled"
    contact_changed = "contact_changed"
    password_reset = "password_reset"
    deactivation_notice = "deactivation_notice"
    domain_expiry = "domain_expiry"
    other = "other"


class ContactChange(BaseModel):
    kind: Literal["phone", "email"] | None = None
    old_last4: str | None = None
    new_last4: str | None = None
    old_email: str | None = None
    new_email: str | None = None


class ExtractedEvent(BaseModel):
    """What ingestion extracts from one email (deterministic parsers first, LLM second)."""

    msg_id: str
    inbox: str  # which connected inbox (root id of the mailbox, e.g. "email_primary")
    date: datetime
    sender: str
    sender_domain: str
    subject: str
    snippet: str = Field(max_length=300)
    service_id: str | None = None  # resolved via policy domains, else None
    service_guess: str | None = None  # free-text name if not resolved
    account_identifier: str | None = None  # usually the To: address
    event: EventKind = EventKind.other
    phone_last4: list[str] = []
    emails_mentioned: list[str] = []
    device: str | None = None
    contact_change: ContactChange | None = None
    deadline: date | None = None
    confidence: float = 0.5


class Evidence(BaseModel):
    id: str
    msg_id: str
    inbox: str
    date: datetime
    sender: str
    subject: str
    snippet: str
    event: EventKind


# ---------------------------------------------------------------- scenarios and explanations
class ScenarioKind(StrEnum):
    takeover = "takeover"  # a stranger gains the roots (recycled number, re-registered domain)
    lockout = "lockout"  # the user loses the roots (SIM dropped, college email closed, phone lost)


class ScenarioRequest(BaseModel):
    kind: ScenarioKind
    root_ids: list[str]  # one or more roots gained (takeover) or lost (lockout)


class Reached(BaseModel):
    node_id: str
    label: str  # display
    node_type: Literal["Account", "Root"]
    round: int
    via_method: str | None = None


class ScenarioResult(BaseModel):
    id: str
    kind: ScenarioKind
    root_ids: list[str]
    actor: Literal["stranger", "user"]
    rounds: int
    # takeover: accounts the stranger controls. lockout: accounts the user can no longer reach.
    affected_accounts: list[Reached]
    direct_accounts: list[str]  # depth-1 view: accounts a single root alone opens (or loses)
    unknown_accounts: list[str]  # modelled=False accounts touching these roots: "unknown, not safe"
    total_accounts: int
    ms: float


class PathStep(BaseModel):
    from_id: str
    from_label: str
    to_id: str
    to_label: str
    method_id: str
    method_label: str
    round: int
    evidence: list[Evidence] = []


class Explanation(BaseModel):
    scenario_id: str
    account_id: str
    outcome: Literal["path", "not_affected", "not_in_graph"]
    steps: list[PathStep] = []  # ordered from the seed root to the account


# ---------------------------------------------------------------- plans and changes
class ChangeStatus(StrEnum):
    proposed = "proposed"
    approved = "approved"
    running = "running"
    awaiting_otp = "awaiting_otp"
    awaiting_user = "awaiting_user"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class Change(BaseModel):
    id: str
    plan_id: str
    order: int
    account_id: str
    account_label: str
    role: UseRole
    from_root: str
    to_root: str | None
    tier: Literal[1, 2, 3, 4]
    requires_old_root: bool
    due: date | None = None  # must finish before this (old root still usable)
    exposure_removed: int = 0  # accounts no longer affected after this step
    status: ChangeStatus = ChangeStatus.proposed
    settings_url: str | None = None
    note: str | None = None


class Plan(BaseModel):
    id: str
    kind: ScenarioKind  # which risk this plan removes
    old_root: str
    new_root: str | None
    deadline: date | None
    feasible: bool
    exposure_before: int
    exposure_after: int
    steps: list[Change]
    created_at: datetime


# ---------------------------------------------------------------- execution
class ExecStep(BaseModel):
    change_id: str
    kind: Literal["progress", "screenshot", "need_otp", "need_user", "done", "failed"]
    message: str
    channel: str | None = None  # need_otp: e.g. "sms:••7788"
    url: str | None = None  # need_user: deep link; screenshot: image url
    at: datetime


# ---------------------------------------------------------------- signals, trace
class SignalKind(StrEnum):
    reissue_countdown = "reissue_countdown"
    closing_email = "closing_email"
    domain_expiry = "domain_expiry"
    stale_root = "stale_root"
    new_device = "new_device"
    missed_account = "missed_account"
    policy_event = "policy_event"


class Signal(BaseModel):
    id: str
    kind: SignalKind
    root_id: str | None
    at: datetime
    title: str
    detail: str
    deadline: date | None = None
    status: Literal["open", "acted", "dismissed"] = "open"


class ToolCallRecord(BaseModel):
    id: str
    at: datetime
    tool: str
    args: dict[str, Any]
    query_name: str | None  # name of the .cypher file that ran
    ms: float
    rows: int
    outcome: Literal["path", "memory", "not_in_graph", "unknown_root", "ok", "error"]


class GraphEvent(BaseModel):
    """Published on Redis channel lapse:events:<uid> and streamed to the web app over SSE."""

    type: Literal["ingest", "graph", "scenario", "plan", "exec", "signal", "trace", "chat"]
    uid: str
    at: datetime
    data: dict[str, Any]
