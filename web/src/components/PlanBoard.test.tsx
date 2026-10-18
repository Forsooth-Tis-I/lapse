import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { planSchema, scenarioResultSchema } from "../api/contracts";
import { PlanBoard } from "./PlanBoard";

afterEach(cleanup);

const basePlan = {
  id: "plan_phone",
  kind: "takeover",
  old_root: "phone_old",
  new_root: "phone_new",
  deadline: null,
  feasible: true,
  exposure_before: 10,
  exposure_after: 0,
  created_at: "2026-10-17T10:00:00Z",
  steps: [],
};

function showPlan(value: unknown) {
  render(<PlanBoard plans={[planSchema.parse(value)]} creating={false} onCreate={() => {}} onChange={() => {}} />);
}

describe("planner details", () => {
  it("shows overlapping risk components separately from the distinct total and keeps unknowns visible at zero", () => {
    showPlan({
      ...basePlan,
      takeover_before: 8,
      takeover_after: 0,
      lockout_before: 4,
      lockout_after: 0,
      remaining_accounts: [],
      unknown_accounts: ["splitwise"],
      note: "Splitwise remains unknown after these changes.",
    });

    expect(screen.getByText("0/0 verified · 10 → 0 distinct accounts affected")).toBeVisible();
    expect(screen.getByText("8 → 0")).toBeVisible();
    expect(screen.getByText("4 → 0")).toBeVisible();
    expect(screen.getByText("None under the methods we model")).toBeVisible();
    expect(screen.getByText("Unknown, not safe")).toBeVisible();
    expect(screen.getByText("splitwise")).toBeVisible();
    expect(screen.getByText("Splitwise remains unknown after these changes.")).toBeVisible();
    expect(screen.queryByText("Additional planner details")).not.toBeInTheDocument();
  });

  it("shows grouped roles, manual titles and instructions for Swiggy and Zomato", () => {
    showPlan({
      ...basePlan,
      exposure_after: 1,
      remaining_accounts: ["swiggy"],
      steps: ["Swiggy", "Zomato"].map((name, index) => ({
        id: `change_${index}`,
        plan_id: "plan_phone",
        order: index + 1,
        account_id: name.toLowerCase(),
        account_label: name,
        role: "login_phone",
        roles: ["login_phone", "recovery_phone"],
        title: `Update all phone roles in ${name}`,
        from_root: "phone_old",
        to_root: "phone_new",
        tier: 3,
        requires_old_root: true,
        note: `Open ${name} settings and update your phone manually.`,
      })),
    });

    for (const name of ["Swiggy", "Zomato"]) {
      expect(screen.getByText(`Update all phone roles in ${name}`)).toBeVisible();
      expect(screen.getByText(`Open ${name} settings and update your phone manually.`)).toBeVisible();
    }
    expect(screen.getAllByText("Roles: login phone, recovery phone")).toHaveLength(2);
    const remaining = screen.getByText("Still affected after this plan").closest("div");
    expect(remaining).not.toBeNull();
    if (remaining) expect(within(remaining).getByText("Swiggy")).toBeVisible();
  });

  it("accepts older plans without making up a component count and preserves future planner details", () => {
    const plan = planSchema.parse({ ...basePlan, future_detail: "Contact support" });
    expect(plan.future_detail).toBe("Contact support");
    showPlan(plan);
    expect(screen.queryByText("Takeover")).not.toBeInTheDocument();
    expect(screen.queryByText("Lockout")).not.toBeInTheDocument();
    expect(screen.getByText("Additional planner details")).toBeVisible();
  });

  it("retains optional lockout tiers from scenario responses", () => {
    const scenario = {
      id: "scenario_college",
      kind: "lockout",
      root_ids: ["email_college"],
      actor: "user",
      rounds: 1,
      affected_accounts: [],
      direct_accounts: [],
      unknown_accounts: [],
      total_accounts: 4,
      ms: 1,
    };
    const reached = { node_id: "canva", label: "Canva", node_type: "Account", round: 1, via_method: null };
    expect(scenarioResultSchema.parse(scenario).recovery_lost_accounts).toBeUndefined();
    const result = scenarioResultSchema.parse({ ...scenario, recovery_lost_accounts: [reached], lost_now_accounts: [] });
    expect(result.recovery_lost_accounts).toEqual([reached]);
    expect(result.lost_now_accounts).toEqual([]);
  });
});

describe("root selection", () => {
  const roots = [
    {id: "phone_old", kind: "phone", label: "••4321", status: "retiring"},
    {id: "email_college", kind: "email", label: "student@example.edu", status: "closing"},
  ] as Parameters<typeof PlanBoard>[0]["roots"];

  it("switches roots without a submit and builds only for the chosen root", () => {
    const onSelectRoot = vi.fn();
    const onCreateRoot = vi.fn();
    render(<PlanBoard plans={[]} roots={roots} selectedRoot="email_college" onSelectRoot={onSelectRoot} onCreateRoot={onCreateRoot} creating={false} onCreate={() => {}} onChange={() => {}} />);
    expect(screen.queryByRole("heading", {name: "••4321"})).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", {name: "Root to retire"}), {target: {value: "phone_old"}});
    expect(onSelectRoot).toHaveBeenCalledWith("phone_old");
    fireEvent.click(screen.getByRole("button", {name: "Build my fix plan"}));
    expect(onCreateRoot).toHaveBeenCalledWith("email_college");
  });
});
