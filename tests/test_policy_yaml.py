import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from lapse.contracts import CarrierRule, ChangeProcedure, MethodTemplate, Service, ServicePolicy, UseRole

POLICY_DIR = Path(__file__).resolve().parents[1] / "lapse" / "policy"
SERVICE_ROWS = yaml.safe_load((POLICY_DIR / "services.yaml").read_text())["services"]
CARRIER_ROWS = yaml.safe_load((POLICY_DIR / "carriers.yaml").read_text())["carriers"]
EXPECTED_SERVICES = {
    "google",
    "microsoft",
    "apple",
    "github",
    "amazon_in",
    "amazon_com",
    "paypal",
    "linkedin",
    "x",
    "instagram",
    "facebook",
    "discord",
    "reddit",
    "dropbox",
    "notion",
    "figma",
    "canva",
    "coursera",
    "slack",
    "spotify",
    "netflix",
    "swiggy",
    "zomato",
    "paytm",
    "generic_in_bank",
    "college_workspace",
}


def test_policy_inventory_and_unique_ids():
    ids = [row["service"]["id"] for row in SERVICE_ROWS]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED_SERVICES
    carrier_ids = [row["id"] for row in CARRIER_ROWS]
    assert len(carrier_ids) == len(set(carrier_ids))
    assert {"jio_in", "airtel_in", "vi_in", "bsnl_in"} <= set(carrier_ids)
    assert any(row["country"] == "US" for row in CARRIER_ROWS)


@pytest.mark.parametrize("row", SERVICE_ROWS, ids=lambda row: row["service"]["id"])
def test_service_contract_and_methods(row):
    policy = ServicePolicy.model_validate(row)
    assert set(row) == {"service", "verified_at", "methods", "change"}
    assert set(row["service"]) <= Service.model_fields.keys()
    assert isinstance(policy.verified_at, date)
    assert policy.service.doc_url
    ids = [method.id for method in policy.methods]
    assert len(ids) == len(set(ids)), policy.service.id
    assert policy.methods or not policy.service.modelled
    for raw_method, method in zip(row["methods"], policy.methods, strict=True):
        assert set(raw_method) <= MethodTemplate.model_fields.keys()
        assert method.doc_url and urlsplit(method.doc_url).scheme == "https"
        assert method.needs_roles or method.needs_password
        assert all(role in UseRole for role in method.needs_roles)
        assert len(method.needs_roles) == len(set(method.needs_roles))


@pytest.mark.parametrize("row", SERVICE_ROWS, ids=lambda row: row["service"]["id"])
def test_change_contract_and_confirmation_regexes(row):
    policy = ServicePolicy.model_validate(row)
    roots = [change.root_kind for change in policy.change]
    assert len(roots) == len(set(roots))
    for raw_change, change in zip(row["change"], policy.change, strict=True):
        assert set(raw_change) <= ChangeProcedure.model_fields.keys()
        assert change.root_kind in {"phone", "email"}
        assert change.tier in {1, 2, 3, 4}
        assert set(change.requires) <= {
            "password",
            "old_otp",
            "new_otp",
            "email_otp_old",
            "email_otp_new",
            "in_person",
        }
        assert change.doc_url and urlsplit(change.doc_url).scheme == "https"
        assert change.settings_url is None or urlsplit(change.settings_url).scheme == "https"
        for pattern in change.confirmation_patterns:
            assert pattern
            re.compile(pattern)


@pytest.mark.parametrize("row", CARRIER_ROWS, ids=lambda row: row["id"])
def test_carrier_contract(row):
    carrier = CarrierRule.model_validate(row)
    assert set(row) == CarrierRule.model_fields.keys()
    assert carrier.reissue_after_days > 0
    assert carrier.country in {"IN", "US"}
    assert urlsplit(carrier.source_url).scheme == "https"


@pytest.mark.parametrize(
    "service_id,root_kind,completed,pending",
    [
        (
            "google",
            "phone",
            "Your recovery phone was changed.",
            "Verify your recovery phone: use the code to finish adding your number.",
        ),
        (
            "google",
            "email",
            "Your recovery email has been updated.",
            "Verify your recovery email using this code.",
        ),
        (
            "apple",
            "phone",
            "Your trusted phone number has been updated.",
            "Review your trusted phone number to keep your account secure.",
        ),
    ],
)
def test_notification_patterns_require_completed_change(service_id, root_kind, completed, pending):
    policy = next(
        ServicePolicy.model_validate(row) for row in SERVICE_ROWS if row["service"]["id"] == service_id
    )
    procedure = next(change for change in policy.change if change.root_kind == root_kind)
    assert any(re.search(pattern, completed) for pattern in procedure.confirmation_patterns)
    assert not any(re.search(pattern, pending) for pattern in procedure.confirmation_patterns)
