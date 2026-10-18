from datetime import timedelta
from pathlib import Path

import yaml
from pydantic import ValidationError

from lapse.contracts import Root
from lapse.graph import db
from lapse.policy.loader import default_policy_paths, load_policy_file


def _validate_root(props: dict) -> Root:
    try:
        return Root.model_validate(props)
    except ValidationError:
        raise ValueError("Invalid persona root definition") from None


def load_persona_local(uid: str, path="persona.local.yaml", *, trace=None) -> dict:
    try:
        persona = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError:
        raise ValueError("Invalid persona YAML") from None
    if not isinstance(persona, dict):
        raise TypeError("Persona must be a YAML mapping")
    carriers = [
        carrier for policy_path in default_policy_paths() for carrier in load_policy_file(policy_path)[1]
    ]
    roots = []
    for item in persona.get("phones", []):
        props = dict(item)
        if "x" in str(props.get("e164", "")).lower():
            raise ValueError("Persona file still contains placeholder values; replace them before onboarding")
        carrier_name = str(props.get("carrier", ""))
        country = str(props.get("country", "")).upper()
        matches = [
            carrier
            for carrier in carriers
            if carrier_name.casefold() in {carrier.id.casefold(), carrier.name.casefold()}
            and (not country or carrier.country.upper() == country)
        ]
        carrier = matches[0] if len(matches) == 1 else None
        digits = "".join(character for character in props.get("e164", "") if character.isdigit())
        last4 = str(props.get("last4") or digits[-4:])
        if len(last4) != 4 or not last4.isdigit():
            raise ValueError("Each phone must provide four trailing digits")
        props.update(
            kind="phone",
            last4=last4,
            label=f"••{last4} ({carrier.name if carrier else carrier_name or 'unknown'})",
            carrier=carrier.id if carrier else carrier_name or None,
            country=country or (carrier.country if carrier else None),
            reissue_after=None,
        )
        root = _validate_root(props)
        if carrier and root.drop_at:
            root.reissue_after = root.drop_at + timedelta(days=carrier.reissue_after_days)
        roots.append(root)
    for item in persona.get("emails", []):
        props = dict(item)
        props["email_kind"] = props.pop("kind", props.get("email_kind", "personal"))
        props["hosted_by_service"] = props.pop("hosted_by", props.get("hosted_by_service"))
        props["address"] = props["address"].strip().lower()
        if props["address"] in {"you.demo@gmail.com", "you.college.stand-in@gmail.com"}:
            raise ValueError("Persona file still contains placeholder values; replace them before onboarding")
        props.update(kind="email", label=props["address"])
        roots.append(_validate_root(props))
    for item in persona.get("devices", []):
        props = dict(item)
        props["device_kind"] = props.pop("kind", props.get("device_kind"))
        props.update(kind="device", label=props["name"])
        roots.append(_validate_root(props))
    if len({root.id for root in roots}) != len(roots):
        raise ValueError("Persona root ids must be unique")

    g = db.user_graph(uid)
    db.ensure_schema(g)
    user = {"uid": uid, "name": persona.get("display_name")}
    user.update({key: persona[key] for key in ("tz", "telegram_chat_id") if key in persona})
    db.run(g, "onboarding_user", {"props": user}, write=True, trace=trace)
    counts = {"users": 1, "roots": len(roots)}
    for kind in ("phone", "email", "device"):
        batch = [root.model_dump(mode="json", exclude_unset=True) for root in roots if root.kind == kind]
        if batch:
            db.run(g, f"onboarding_{kind}", {"roots": batch}, write=True, trace=trace)
        counts[f"{kind}s"] = len(batch)
    return counts


def apply_declared_uses(uid: str, path="persona.local.yaml", *, trace=None) -> int:
    """Write user-declared USES edges (facts emails never show, e.g. Google's 2-Step phone).

    persona YAML:
      declared_uses:
        - {service: google, account: email_primary, role: sms_2fa, root: phone_old}
    `account` names the email root the account signs in with. Edges are confirmed, source=declared.
    A declared use asserts the account exists: if ingest has not discovered it, it is created with the
    id ingest would give it, so a later discovery merges instead of duplicating.
    """
    from lapse.contracts import UseRole
    from lapse.ingest.writer import _id
    from lapse.policy.compile import compile_user_graph

    persona = yaml.safe_load(Path(path).read_text()) or {}
    g = db.user_graph(uid)
    policies = [policy for p in default_policy_paths() for policy in load_policy_file(p)[0]]
    services = {policy.service.id: policy.service for policy in policies}
    touched: set[str] = set()
    for item in persona.get("declared_uses") or []:
        role = UseRole(item["role"])
        service = services.get(item["service"])
        if service is None:
            raise ValueError(f"Declared use names an unknown service: {item['service']}")
        address = next(
            iter(db.run(g, "onboarding_root_address", {"root_id": item["account"]}, trace=trace).rows),
            {},
        ).get("address")
        if not address:
            raise ValueError(f"Declared use needs an email root as its account: {item['account']}")
        identifier = address.strip().lower()
        db.run(
            g,
            "onboarding_declared_account",
            {
                "service": service.model_dump(mode="json", exclude_none=True),
                "login_root": item["account"],
                "identifier": identifier,
                "account_id": _id("account", service.id, identifier),
            },
            write=True,
            trace=trace,
        )
        rows = db.run(
            g,
            "onboarding_declared_use",
            {
                "service_id": item["service"],
                "account_root": item["account"],
                "role": role.value,
                "root_id": item["root"],
            },
            write=True,
            trace=trace,
        ).rows
        touched.update(row["account_id"] for row in rows)
    if touched:
        compile_user_graph(g, policies, account_ids=sorted(touched))
    return len(touched)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Load a persona file and its declared uses into a user graph."
    )
    parser.add_argument("--uid", required=True)
    parser.add_argument("--path", default="persona.local.yaml")
    args = parser.parse_args()
    counts = load_persona_local(args.uid, args.path)
    counts["declared_accounts"] = apply_declared_uses(args.uid, args.path)
    print(counts)


if __name__ == "__main__":
    main()
