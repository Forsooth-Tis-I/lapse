from __future__ import annotations

import re
from pathlib import Path

ENTITY_FIELDS = {
    "id",
    "node_id",
    "account_id",
    "root_id",
    "service_id",
    "from_id",
    "to_id",
    "old_root",
    "new_root",
    "from_root",
    "to_root",
    "label",
    "display",
    "name",
    "account_label",
    "from_label",
    "to_label",
    "identifier",
    "address",
    "carrier",
    "last4",
}
ENTITY_LISTS = {"root_ids", "direct_accounts", "unknown_accounts"}
PROSE = set(Path(__file__).with_name("prompts").joinpath("grounded_words.txt").read_text().split())


def entities(results):
    values = set()

    def walk(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and (key in ENTITY_FIELDS or key in ENTITY_LISTS) and value:
            values.add(value)

    for result in results:
        walk(result)
    return values


def has_unknown(results):
    return any(
        isinstance(result, dict)
        and (result.get("outcome") in {"not_in_graph", "unknown_root"} or result.get("unknown_accounts"))
        for result in results
    )


def grounded(text: str, results: list) -> bool:
    if not text or "under the methods we model" not in text.casefold():
        return False
    if has_unknown(results) and "unknown, not safe" not in text.casefold():
        return False
    remainder = text
    for value in sorted(entities(results), key=len, reverse=True):
        remainder = re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", " ", remainder, flags=re.IGNORECASE)
    words = re.findall(r"[\w@.+•-]+", remainder.casefold())
    return all(
        word.strip(".-") in PROSE or re.fullmatch(r"\d{1,3}(?:[.,]\d{1,2})?|t[1-4]", word)
        for word in words
        if word.strip(".-")
    )


def templated(results: list) -> str:
    for result in reversed(results):
        if not isinstance(result, dict):
            if isinstance(result, list) and result:
                labels = [
                    item.get("label", item.get("id", "")) if isinstance(item, dict) else str(item)
                    for item in result
                ]
                return f"Stored in the graph: {', '.join(labels)}. Choose a root to show risk under the methods we model."
            continue
        if result.get("outcome") in {"error", "not_in_graph", "unknown_root"}:
            return f"{result['message']} Choose a known root to review under the methods we model."
        if "affected_accounts" in result:
            direct = len(result["direct_accounts"])
            indirect = len(
                {a["node_id"] for a in result["affected_accounts"]} - set(result["direct_accounts"])
            )
            labels = ", ".join(a["label"] for a in result["affected_accounts"]) or "none"
            unknown = result.get("unknown_accounts", [])
            extra = f" Unknown, not safe: {', '.join(unknown)}." if unknown else ""
            return (
                f"Under the methods we model, {result['kind']}: directly: {direct}; "
                f"through other accounts: {indirect} more. Affected accounts: {labels}.{extra} Plan the fix next."
            )
        if "exposure_before" in result:
            steps = (
                "; ".join(
                    f"{s['order']}. {s['account_label']} (T{s['tier']}, {s['status']})"
                    for s in result["steps"]
                )
                or "No changes proposed"
            )
            feasibility = "" if result["feasible"] else " The full plan is infeasible before the deadline."
            return (
                f"Under the methods we model, planned exposure: {result['exposure_before']} to "
                f"{result['exposure_after']}. {steps}.{feasibility} Review the steps before approval."
            )
        if result.get("outcome") == "not_affected":
            return "This account is not affected in this scenario under the methods we model. Review its methods next."
        if result.get("outcome") == "path":
            path = "; ".join(
                f"{s['from_label']} to {s['to_label']} through {s['method_label']}" for s in result["steps"]
            )
            return (
                f"Under the methods we model: {path}. Review all required method branches, then plan the fix."
            )
        if "candidates" in result:
            choices = ", ".join(c["label"] for c in result["candidates"])
            return f"Choose a matching root or account: {choices}. Then show risk under the methods we model."
        if "account" in result:
            account = result["account"]
            return (
                f"{account.get('display', account['id'])} is in the graph. "
                "Choose a root to explain its risk under the methods we model."
            )
    return "Choose a known root to show risk or plan the fix under the methods we model. Unknown means unknown, not safe."
