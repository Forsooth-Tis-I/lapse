import { describe, it, expect } from "vitest";
import { displayReach } from "./AccountGraph";
import { createMockApi } from "../api/mock";

describe("live mailbox display", () => {
  it("places an omitted mailbox Root in round 2 without counting it as an account", async () => {
    const api = createMockApi();
    const graph = await api.getGraph();
    const result = await api.createScenario({kind: "takeover", root_ids: ["phone_old"]});
    result.affected_accounts = result.affected_accounts.filter((item) => item.node_type === "Account");
    const reached = displayReach(graph, [result]);
    expect(reached.find((item) => item.node_id === "email_primary")).toMatchObject({node_type: "Root", round: 2, kind: "takeover"});
    expect(reached.filter((item) => item.node_type === "Account")).toHaveLength(10);
    expect(result.affected_accounts).toHaveLength(10);
    expect(reached.some((item) => item.node_id === "splitwise")).toBe(false);
  });
});

describe("node labels", () => {
  it("splits service and address and keeps long addresses inside the node", async () => {
    const { nodeLabel } = await import("./AccountGraph");
    expect(
      nodeLabel({ id: "a", label: "Google · averyveryverylongname@gmail.com", node_type: "Account" }),
    ).toBe("Google\naveryveryvery…@gmail.com");
    expect(
      nodeLabel({
        id: "r",
        label: "me@example.com",
        node_type: "Root",
        root: { id: "r", kind: "email", label: "me@example.com", status: "active" } as never,
      }),
    ).toBe("Inbox\nme@example.com");
  });
});
