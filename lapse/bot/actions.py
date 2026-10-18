from __future__ import annotations

from lapse.contracts import Change, Signal, UseRole
from lapse.graph import db


def list_signals(uid: str, *, trace=None) -> list[Signal]:
    return [
        Signal.model_validate({"root_id": None, **row["signal"]})
        for row in db.run(db.user_graph(uid), "bot_signals", trace=trace).rows
    ]


def dismiss_signal(uid: str, signal_id: str, *, trace=None) -> None:
    rows = db.run(
        db.user_graph(uid), "bot_dismiss_signal", {"signal_id": signal_id}, write=True, trace=trace
    ).rows
    if not rows:
        raise ValueError("Signal not found")


def get_change(uid: str, change_id: str, *, trace=None) -> Change:
    rows = db.run(db.user_graph(uid), "planner_get_change", {"change_id": change_id}, trace=trace).rows
    if not rows:
        raise ValueError("Change not found")
    return Change.model_validate({"to_root": None, **rows[0]["change"]})


def confirm_use(uid: str, account_id: str, root_id: str, role: str, value: bool, *, trace=None) -> None:
    from lapse.policy.compile import compile_user_graph
    from lapse.policy.loader import default_policy_paths, load_policy_file

    if type(value) is not bool:
        raise ValueError("Confirmation must be yes or no")
    g = db.user_graph(uid)
    rows = db.run(
        g,
        "bot_confirm_use" if value else "bot_remove_use",
        {"account_id": account_id, "root_id": root_id, "role": UseRole(role).value},
        write=True,
        trace=trace,
    ).rows
    if not rows:
        raise ValueError("Account use not found")
    policies = [policy for path in default_policy_paths() for policy in load_policy_file(path)[0]]
    compile_user_graph(g, policies, account_ids=[account_id])


def list_accounts(uid: str) -> list[dict]:
    return [row["account"] for row in db.run(db.user_graph(uid), "wp4_accounts").rows]
