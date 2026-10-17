from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lapse.config import ROOT_DIR
from lapse.contracts import CarrierRule, ServicePolicy


class _PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    services: list[ServicePolicy] = Field(default_factory=list)
    carriers: list[CarrierRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_templates(self) -> "_PolicyFile":
        service_ids = [policy.service.id for policy in self.services]
        carrier_ids = [carrier.id for carrier in self.carriers]
        if len(set(service_ids)) != len(service_ids) or len(set(carrier_ids)) != len(carrier_ids):
            raise ValueError("Duplicate service or carrier id")
        for policy in self.services:
            ids = [method.id for method in policy.methods]
            if len(set(ids)) != len(ids):
                raise ValueError(f"Duplicate method id for {policy.service.id}")
            for method in policy.methods:
                if not method.needs_roles and not method.needs_password:
                    raise ValueError(f"Zero-need method {method.id} must need a password")
                if len(set(method.needs_roles)) != len(method.needs_roles):
                    raise ValueError(f"Duplicate need role in {method.id}")
        return self


def load_policy_file(path: str | Path) -> tuple[list[ServicePolicy], list[CarrierRule]]:
    data = _PolicyFile.model_validate(yaml.safe_load(Path(path).read_text()))
    return data.services, data.carriers


def default_policy_paths() -> list[Path]:
    paths = [ROOT_DIR / "lapse/policy/services.yaml", ROOT_DIR / "lapse/policy/carriers.yaml"]
    return paths if all(path.is_file() for path in paths) else [ROOT_DIR / "fixtures/policy.yaml"]
