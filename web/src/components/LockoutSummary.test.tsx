import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { scenarioResultSchema } from "../api/contracts";
import { LockoutSummary } from "./LockoutSummary";

afterEach(cleanup);
const legacy = { id: "college", kind: "lockout", root_ids: ["email_college"], actor: "user", rounds: 0, affected_accounts: [], direct_accounts: [], unknown_accounts: ["splitwise"], total_accounts: 17, ms: 1 };

it("does not invent recovery loss for a legacy zero-lockout response", () => {
  render(<LockoutSummary results={[scenarioResultSchema.parse(legacy)]} />);
  expect(screen.getByText("0 lost now")).toBeVisible();
  expect(screen.getByText("Recovery loss not reported")).toBeVisible();
  expect(screen.getByText(/Password login can still work/)).toBeVisible();
});

it("renders both reported tiers, counts only accounts and deduplicates shared results", () => {
  const result = scenarioResultSchema.parse({ ...legacy,
    lost_now_accounts: [{node_id: "notion", label: "Notion", node_type: "Account", round: 1}],
    recovery_lost_accounts: [
      {node_id: "canva", label: "Canva", node_type: "Account", round: 1},
      {node_id: "email_college", label: "College", node_type: "Root", round: 0},
    ],
  });
  render(<LockoutSummary results={[result, {...result, id: "second"}]} />);
  expect(screen.getByText("1 lost now")).toBeVisible();
  expect(screen.getByText("Notion")).toBeVisible();
  expect(screen.getByText("1 with recovery lost")).toBeVisible();
  expect(screen.getByText("No way back if you forget the password: Canva.")).toBeVisible();
});
