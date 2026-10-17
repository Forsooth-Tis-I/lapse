from __future__ import annotations

import argparse
import json
import math
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from uuid import uuid4

from redis.exceptions import ResponseError

from lapse.agent.tools import REGISTRY
from lapse.config import ROOT_DIR
from lapse.contracts import ScenarioRequest
from lapse.graph import db
from lapse.graph.closure import closure
from lapse.graph.planner import plan_for_root
from lapse.graph.scenarios import run_scenario
from lapse.graph.views import stats
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

TOKEN = re.compile(r"<!--\s*/?claim\b", re.IGNORECASE)
OPEN = re.compile(r"<!-- claim:([a-z][a-z0-9_.]*) -->")
CLOSE = "<!-- /claim -->"
INVENTORY_OPEN = "<!-- query-inventory -->"
INVENTORY_CLOSE = "<!-- /query-inventory -->"
NUMBER = r"(?:\d+(?:\.\d+)?)"
RANGE = re.compile(rf"({NUMBER})\s*[-–]\s*({NUMBER})")


@dataclass(frozen=True)
class Claim:
    key: str
    start: int
    end: int
    value: str


def parse_claims(text: str) -> list[Claim]:
    claims = []
    position = 0
    while token := TOKEN.search(text, position):
        opening = OPEN.match(text, token.start())
        if opening is None:
            raise ValueError(f"Malformed claim marker at character {token.start()}")
        closing = text.find(CLOSE, opening.end())
        next_token = TOKEN.search(text, opening.end())
        if closing < 0 or next_token is None or next_token.start() != closing:
            raise ValueError(f"Unclosed or nested claim: {opening[1]}")
        claims.append(Claim(opening[1], opening.end(), closing, text[opening.end() : closing]))
        position = closing + len(CLOSE)
    return claims


def account_count(result: object, *fields: str) -> int | None:
    for field in fields:
        value = getattr(result, field, None)
        if value is not None:
            return value if isinstance(value, int) else len(value)
    return None


def scenario_claims(prefix: str, result: object) -> dict[str, int | None]:
    values = {f"{prefix}.full": account_count(result, "affected_accounts", "full_accounts", "full")}
    if prefix.startswith("takeover_"):
        values.update(
            {
                f"{prefix}.direct": account_count(result, "direct_accounts", "direct"),
                f"{prefix}.unknown": account_count(result, "unknown_accounts", "unknown"),
            }
        )
    else:
        for field in ("lost_now", "recovery_lost"):
            fields = (f"{field}_accounts", field)
            if field == "lost_now":
                fields += ("affected_accounts",)
            values[f"{prefix}.{field}"] = account_count(result, *fields)
    return values


@contextmanager
def verification_user(uid: str | None):
    private_uid = f"verify-claims-{uuid4().hex}"
    graph = db.user_graph(private_uid)
    try:
        if uid is None:
            policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
            _, carriers = load_policy_file(ROOT_DIR / "lapse/policy/carriers.yaml")
            load_persona(graph, policies, carriers)
        else:
            db.copy_graph(db.user_graph(uid), graph.name)
        yield private_uid
    finally:
        try:
            graph.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


def collect_claims(uid: str) -> dict[str, int | float | None]:
    counts = stats(uid)
    values: dict[str, int | float | None] = {
        "graph.nodes": counts["nodes"],
        "graph.edges": counts["edges"],
        "queries.count": len(list(db.QUERY_DIR.glob("*.cypher"))),
        "tools.count": len(REGISTRY),
    }
    for label in ("Account", "Root", "Method"):
        values[f"graph.{label.lower()}s"] = counts["by_label"].get(label, 0)
    for prefix, kind, roots in (
        ("takeover_phone_old", "takeover", ["phone_old"]),
        ("lockout_email_college", "lockout", ["email_college"]),
        ("compound_lockout", "lockout", ["phone_old", "email_college"]),
    ):
        result = run_scenario(uid, ScenarioRequest(kind=kind, root_ids=roots))
        values.update(scenario_claims(prefix, result))
    plan = plan_for_root(uid, "phone_old", "phone_new")
    values.update(
        {
            "plan_phone_old.before": plan.exposure_before,
            "plan_phone_old.after": plan.exposure_after,
            "plan_phone_old.steps": len(plan.steps),
            "closure.ms": median(closure(db.user_graph(uid), ["phone_old"]).ms for _ in range(5)),
        }
    )
    return values


def format_value(key: str, value: float | None) -> str:
    if value is None:
        return "not reported"
    if key == "closure.ms":
        return f"0-{max(10, math.ceil(value * 2 / 10) * 10)}"
    return str(value)


def matches(key: str, expected: str, actual: float | None) -> bool:
    expected = expected.strip()
    if actual is None:
        return expected == "not reported"
    if key != "closure.ms":
        return expected == str(actual)
    if interval := RANGE.fullmatch(expected):
        low, high = map(float, interval.groups())
        return low <= actual <= high
    if re.fullmatch(NUMBER, expected):
        return math.isclose(float(expected), actual, rel_tol=0.5, abs_tol=1)
    return False


def render_claims(text: str, values: dict[str, int | float | None], *, write: bool = False) -> str:
    claims = parse_claims(text)
    errors = []
    for claim in claims:
        if claim.key not in values:
            errors.append(f"Unknown claim: {claim.key}")
        elif not write and not matches(claim.key, claim.value, values[claim.key]):
            errors.append(f"{claim.key}: documented {claim.value!r}, measured {values[claim.key]}")
    if errors:
        raise ValueError("\n".join(errors))
    if write:
        for claim in reversed(claims):
            text = text[: claim.start] + format_value(claim.key, values[claim.key]) + text[claim.end :]
    return text


def query_inventory(query_dir: Path, descriptions_path: Path) -> str:
    descriptions = json.loads(descriptions_path.read_text())
    paths = sorted(query_dir.glob("*.cypher"))
    names = {path.stem for path in paths}
    if set(descriptions) != names:
        missing = sorted(names - set(descriptions))
        extra = sorted(set(descriptions) - names)
        raise ValueError(f"Query descriptions differ from query files: missing={missing}, extra={extra}")
    rows = ["", "| Named query | Description |", "| --- | --- |"]
    for path in paths:
        description = descriptions[path.stem]
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Missing description: {path.stem}")
        description = description.replace("|", "\\|").replace("\n", " ")
        rows.append(f"| [{path.stem}](lapse/graph/queries/{path.name}) | {description} |")
    return "\n".join(rows) + "\n"


def render_inventory(text: str, inventory: str, *, write: bool = False) -> str:
    if not re.search(r"<!--\s*/?query-inventory\b", text, re.IGNORECASE):
        return text
    if text.count(INVENTORY_OPEN) != 1 or text.count(INVENTORY_CLOSE) != 1:
        raise ValueError("Expected one complete query-inventory marker pair")
    start = text.index(INVENTORY_OPEN) + len(INVENTORY_OPEN)
    end = text.index(INVENTORY_CLOSE)
    if end < start:
        raise ValueError("Query inventory markers are reversed")
    if not write and text[start:end] != inventory:
        raise ValueError("Query inventory differs; run verify_claims --write")
    return text[:start] + inventory + text[end:]


def verify_files(
    paths: list[Path],
    values: dict[str, int | float | None],
    *,
    write: bool = False,
    inventory: str | None = None,
) -> int:
    updates = []
    errors = []
    total = 0
    for path in paths:
        try:
            original = path.read_text()
            updated = render_claims(original, values, write=write)
            if inventory is not None:
                updated = render_inventory(updated, inventory, write=write)
            total += len(parse_claims(original))
            updates.append((path, original, updated))
        except (ValueError, OSError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    if write:
        for path, original, updated in updates:
            if original != updated:
                path.write_text(updated)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Markdown claims against the running graph engine.")
    parser.add_argument("paths", nargs="*", type=Path, help="Default: README.md and docs/**/*.md")
    parser.add_argument(
        "--uid", help="Evaluate a private copy of an existing graph; default loads a private fixture graph"
    )
    parser.add_argument(
        "--write", action="store_true", help="Replace marked values with current measurements"
    )
    args = parser.parse_args(argv)
    paths = args.paths or [ROOT_DIR / "README.md", *sorted((ROOT_DIR / "docs").rglob("*.md"))]
    try:
        for path in paths:
            parse_claims(path.read_text())
        with verification_user(args.uid) as uid:
            values = collect_claims(uid)
        print("Current claim registry:")
        for key, value in sorted(values.items()):
            print(f"  {key} = {'unavailable' if value is None else format_value(key, value)}")
        inventory = query_inventory(db.QUERY_DIR, ROOT_DIR / "docs/query-descriptions.json")
        count = verify_files(paths, values, write=args.write, inventory=inventory)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{'Updated' if args.write else 'Verified'} {count} claims in {len(paths)} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
