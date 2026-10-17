from copy import deepcopy
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from lapse.policy import loader


@pytest.fixture
def policy_document():
    return {
        "services": [
            {
                "service": {"id": "mail", "name": "Mail", "domains": ["example.com"]},
                "verified_at": "2026-10-17",
                "methods": [
                    {"id": "reset", "kind": "reset", "label": "Email reset", "needs_roles": ["login_email"]}
                ],
                "change": [{"root_kind": "email", "tier": 1, "requires": ["email_otp_new"]}],
            }
        ],
        "carriers": [
            {
                "id": "vi_in",
                "name": "Vi",
                "country": "IN",
                "reissue_after_days": 90,
                "source_url": "https://example.com/policy",
            }
        ],
    }


def write_document(tmp_path, document):
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


def test_loads_shared_models_and_password_only_method(tmp_path, policy_document):
    policy_document["services"][0]["methods"].append(
        {
            "id": "password",
            "kind": "login",
            "label": "Password sign-in",
            "needs_roles": [],
            "needs_password": True,
        }
    )
    policies, carriers = loader.load_policy_file(write_document(tmp_path, policy_document))

    assert policies[0].service.id == "mail"
    assert policies[0].verified_at == date(2026, 10, 17)
    assert policies[0].methods[0].needs_roles == ["login_email"]
    assert policies[0].methods[1].needs_password is True
    assert policies[0].change[0].requires == ["email_otp_new"]
    assert carriers[0].model_dump() == policy_document["carriers"][0]


@pytest.mark.parametrize("section", ["services", "carriers"])
def test_rejects_duplicate_entity_ids(tmp_path, policy_document, section):
    policy_document[section].append(deepcopy(policy_document[section][0]))
    with pytest.raises(ValidationError, match="Duplicate"):
        loader.load_policy_file(write_document(tmp_path, policy_document))


def test_rejects_duplicate_method_ids(tmp_path, policy_document):
    methods = policy_document["services"][0]["methods"]
    methods.append(deepcopy(methods[0]))
    with pytest.raises(ValidationError, match="Duplicate method"):
        loader.load_policy_file(write_document(tmp_path, policy_document))


@pytest.mark.parametrize(
    "roles, message",
    [
        ([], "Zero-need method"),
        (["login_email", "login_email"], "Duplicate need role"),
        (["unknown_role"], "Input should be"),
    ],
)
def test_rejects_invalid_method_needs(tmp_path, policy_document, roles, message):
    policy_document["services"][0]["methods"][0]["needs_roles"] = roles
    with pytest.raises(ValidationError, match=message):
        loader.load_policy_file(write_document(tmp_path, policy_document))


def test_loads_separate_policy_files(tmp_path, policy_document):
    policies, carriers = loader.load_policy_file(
        write_document(tmp_path, {"services": policy_document["services"]})
    )
    assert [policy.service.id for policy in policies] == ["mail"]
    assert carriers == []
    policies, carriers = loader.load_policy_file(
        write_document(tmp_path, {"carriers": policy_document["carriers"]})
    )
    assert policies == []
    assert [carrier.id for carrier in carriers] == ["vi_in"]


def test_default_paths_use_full_policy_only_when_both_files_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "ROOT_DIR", tmp_path)
    policy_dir = tmp_path / "lapse/policy"
    policy_dir.mkdir(parents=True)
    services = policy_dir / "services.yaml"
    carriers = policy_dir / "carriers.yaml"
    assert loader.default_policy_paths() == [tmp_path / "fixtures/policy.yaml"]
    services.touch()
    assert loader.default_policy_paths() == [tmp_path / "fixtures/policy.yaml"]
    carriers.touch()
    assert loader.default_policy_paths() == [services, carriers]
