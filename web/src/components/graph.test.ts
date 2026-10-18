import { afterEach, describe, it, expect, vi } from "vitest";
import { createElement } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import type { Core, CytoscapeOptions } from "cytoscape";
import { AccountGraph, displayReach } from "./AccountGraph";
import { createMockApi } from "../api/mock";

const instances = vi.hoisted(() => [] as Core[]);
vi.mock("../useReducedMotion", () => ({ useReducedMotion: () => true }));
vi.mock("cytoscape", async (importOriginal) => {
  const actual = await importOriginal<{ default: typeof import("cytoscape") }>();
  const headless = Object.assign((options: CytoscapeOptions) => {
    const cy = actual.default({ ...options, container: undefined, headless: true, styleEnabled: true });
    instances.push(cy);
    return cy;
  }, { use: actual.default.use });
  return { default: headless };
});

afterEach(() => {
  cleanup();
  instances.length = 0;
  vi.unstubAllGlobals();
});

it("keeps modelled accounts neutral until a scenario succeeds", async () => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
  const api = createMockApi();
  const graph = await api.getGraph();
  const props = {
    graph, results: [], depth: "full" as const, selected: null, explanation: null,
    onSelect: () => {}, fixedAccountIds: [],
  };
  const view = render(createElement(AccountGraph, props));
  expect(instances.at(-1)?.nodes(".safe")).toHaveLength(0);
  expect(screen.getByText("UNASSESSED")).toBeVisible();
  const result = await api.createScenario({ kind: "takeover", root_ids: ["phone_old"] });
  view.rerender(createElement(AccountGraph, { ...props, results: [result] }));
  expect(instances.at(-1)?.nodes(".safe").length).toBeGreaterThan(0);
  view.rerender(createElement(AccountGraph, props));
  expect(instances.at(-1)?.nodes(".safe")).toHaveLength(0);
});

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
