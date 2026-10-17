from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr

from lapse.contracts import Account, Root, ScenarioRequest

Nonempty = Annotated[str, Field(min_length=1)]


class ScenarioInput(ScenarioRequest):
    root_ids: list[Nonempty] = Field(min_length=1)


class PlanInput(BaseModel):
    old_root: Nonempty
    new_root: Nonempty | None = None
    deadline: date | None = None


class OtpInput(BaseModel):
    code: SecretStr = Field(min_length=1, max_length=128)


class ChatInput(BaseModel):
    text: Nonempty


class InboxInput(BaseModel):
    host: Nonempty
    username: Nonempty
    app_password: SecretStr = Field(min_length=1)


class PhoneInput(BaseModel):
    number: Nonempty
    carrier: str
    status: Literal["retiring", "active"]
    drop_at: date | None = None
    id: Nonempty | None = None
    country: str = "IN"


class EmailInput(BaseModel):
    id: Nonempty
    address: Nonempty
    kind: Literal["personal", "edu", "work", "custom"] = "personal"
    hosted_by: str | None = None
    status: Literal["active", "closing", "closed"] = "active"
    closes_at: date | None = None


class DeviceInput(BaseModel):
    id: Nonempty
    name: Nonempty
    kind: Literal["phone", "laptop", "key"]
    status: Literal["active", "sold", "lost"] = "active"


class OnboardingInput(BaseModel):
    inboxes: list[InboxInput] = Field(default_factory=list)
    phones: list[PhoneInput] = Field(default_factory=list)
    display_name: str = "Lapse user"
    emails: list[EmailInput] = Field(default_factory=list)
    devices: list[DeviceInput] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: Literal["Root", "Account"]
    root: Root | None = None
    account: Account | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    confirmed: bool
    method_id: str | None = None


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphStats(BaseModel):
    nodes: int
    edges: int
    last_query_ms: float
