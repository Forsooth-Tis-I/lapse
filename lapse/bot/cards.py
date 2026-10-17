from __future__ import annotations

from lapse.contracts import ChangeStatus, Plan, Root, ScenarioResult, Signal

TIERS = {1: "T1 auto", 2: "T2 your code", 3: "T3 you do it", 4: "T4 in person"}
FINISHED = {ChangeStatus.done, ChangeStatus.skipped}


def deadline(value) -> str:
    return f" · due {value}" if value else ""


def depth(result: ScenarioResult) -> str:
    direct = len(result.direct_accounts)
    indirect = len({a.node_id for a in result.affected_accounts} - set(result.direct_accounts))
    return (
        f"Directly: {direct} accounts · Through other accounts: {indirect} more"
        f" · Unknown: {len(result.unknown_accounts)}"
    )


def scenario_card(root: Root, result: ScenarioResult) -> str:
    lines = [depth(result), f"{root.label} · {result.kind.value}", "Under the methods we model."]
    if result.unknown_accounts:
        lines.append("Unmodelled accounts are unknown, not safe.")
    lines.extend(f"• {account.label}" for account in result.affected_accounts[:3])
    lines.append(deadline(root.drop_at or root.closes_at or root.expires_at).lstrip(" ·"))
    return "\n".join(line for line in lines if line)


def plan_card(plan: Plan, result: ScenarioResult) -> str:
    lines = [
        depth(result),
        f"Plan for {plan.old_root}{deadline(plan.deadline)}",
        "Under the methods we model.",
    ]
    if result.unknown_accounts:
        lines.append("Unmodelled accounts are unknown, not safe.")
    if not plan.feasible:
        lines.append("This plan cannot resolve every modelled exposure before the deadline.")
    for step in sorted(plan.steps, key=lambda step: step.order)[:3]:
        lines.append(
            f"{step.order}. {step.account_label} · {TIERS[step.tier]}{deadline(step.due)} · {step.status.value}"
        )
    if len(plan.steps) > 3:
        lines.append(f"+ {len(plan.steps) - 3} more steps in the web plan")
    if not plan.steps:
        lines.append("No steps available. Review the risk in the web app.")
    return "\n".join(lines)


def status_card(roots: list[Root], plans: list[Plan], signals: list[Signal]) -> str:
    lines = ["Roots"]
    lines.extend(
        f"• {root.label} · {root.status.value}{deadline(root.drop_at or root.closes_at or root.expires_at)}"
        for root in roots
    )
    if not roots:
        lines.append("None yet. Add roots in web onboarding.")
    lines.append("\nOpen plans")
    open_plans = [plan for plan in plans if any(step.status not in FINISHED for step in plan.steps)]
    lines.extend(
        f"• {plan.old_root}: {sum(s.status not in FINISHED for s in plan.steps)} steps left"
        f"{deadline(plan.deadline)}"
        for plan in open_plans
    )
    if not open_plans:
        lines.append("None")
    lines.append("\nSignals")
    lines.extend(f"• {signal.title}{deadline(signal.deadline)}" for signal in signals)
    if not signals:
        lines.append("None")
    return "\n".join(lines)
