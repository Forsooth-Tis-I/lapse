import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockApi } from "./mock";
import {
  decodeEvent,
  graphEventSchema,
  rootSchema,
  type UiEvent,
} from "./contracts";
import { createRestApi } from "./index";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("demo API contract", () => {
  it("separates direct accounts, hosted mailbox, downstream accounts, blocked AND and unknown services", async () => {
    const api = createMockApi();
    const result = await api.createScenario({
      kind: "takeover",
      root_ids: ["phone_old"],
    });
    expect(result.direct_accounts).toEqual([
      "google",
      "x",
      "amazon_in",
      "swiggy",
      "zomato",
    ]);
    expect(
      result.affected_accounts
        .filter((item) => item.node_type === "Account")
        .map((item) => item.node_id),
    ).toEqual([
      "google",
      "x",
      "amazon_in",
      "swiggy",
      "zomato",
      "notion",
      "spotify",
      "paypal",
      "dropbox",
      "linkedin",
    ]);
    expect(
      result.affected_accounts.find((item) => item.node_id === "email_primary"),
    ).toMatchObject({ node_type: "Root", round: 2 });
    expect(result.unknown_accounts).toEqual(["splitwise"]);
    expect((await api.explain(result.id, "github")).outcome).toBe(
      "not_affected",
    );
    const dropbox = await api.explain(result.id, "dropbox");
    expect(dropbox.steps.map((step) => step.from_id)).toEqual([
      "phone_old",
      "google",
      "email_primary",
      "phone_old",
    ]);
    expect(
      dropbox.steps
        .filter((step) => step.to_id === "dropbox")
        .map((step) => step.method_id),
    ).toEqual(["dropbox:email_and_sms", "dropbox:email_and_sms"]);
    expect(
      (await api.getGraph()).edges
        .filter((edge) => edge.target === "dropbox")
        .map((edge) => edge.method_id),
    ).toEqual(["dropbox:email_and_sms", "dropbox:email_and_sms"]);
  });

  it("streams closure rounds without changing the stored complete result and unsubscribes", async () => {
    const api = createMockApi();
    const events: UiEvent[] = [];
    const unsubscribe = api.subscribe((event) => events.push(event));
    const result = await api.createScenario({
      kind: "takeover",
      root_ids: ["phone_old"],
    });
    await vi.advanceTimersByTimeAsync(425);
    const event = events.find((item) => item.kind === "scenario");
    expect(
      event?.kind === "scenario" && event.data.affected_accounts.length,
    ).toBe(5);
    expect((await api.getScenario(result.id)).affected_accounts).toHaveLength(
      11,
    );
    unsubscribe();
    const count = events.length;
    await vi.runAllTimersAsync();
    expect(events).toHaveLength(count);
  });

  it("locks out the four college accounts while Google remains reachable", async () => {
    const api = createMockApi();
    const result = await api.createScenario({
      kind: "lockout",
      root_ids: ["email_college"],
    });
    expect(result.affected_accounts.map((item) => item.node_id)).toEqual([
      "figma",
      "canva",
      "coursera",
      "microsoft",
    ]);
    expect((await api.explain(result.id, "google")).outcome).toBe(
      "not_affected",
    );
  });

  it("requires approval and OTP before changing the graph; preserves unknown and the in-person step", async () => {
    const api = createMockApi();
    const result = await api.createScenario({
      kind: "takeover",
      root_ids: ["phone_old"],
    });
    const plan = await api.createPlan({
      old_root: "phone_old",
      new_root: "phone_new",
    });
    const google = plan.steps.find((step) => step.account_id === "google");
    const offline = plan.steps.find((step) => step.tier === 4);
    if (!google || !offline) throw new Error("Missing demo steps");
    await vi.runAllTimersAsync();
    expect((await api.getPlan(plan.id)).steps[0]?.status).toBe("proposed");
    await api.approveChange(google.id);
    await vi.runAllTimersAsync();
    expect((await api.getPlan(plan.id)).steps[0]?.status).toBe("awaiting_otp");
    await expect(api.submitOtp(google.id, "123")).rejects.toThrow("six-digit");
    await api.submitOtp(google.id, "123456");
    await vi.runAllTimersAsync();
    expect(
      (await api.getScenario(result.id)).affected_accounts.map(
        (item) => item.node_id,
      ),
    ).toEqual(["x", "amazon_in", "swiggy", "zomato"]);
    expect((await api.getScenario(result.id)).unknown_accounts).toEqual([
      "splitwise",
    ]);
    expect(
      (await api.getGraph()).edges.find(
        (item) => item.target === "google" && item.source === "phone_new",
      ),
    ).toBeDefined();
    expect(JSON.stringify(await api.getTrace())).not.toContain("123456");
    const recreated = await api.createPlan({
      old_root: "phone_old",
      new_root: "phone_new",
    });
    expect(recreated.steps.map((step) => [step.account_id, step.tier])).toEqual(
      [
        ["x", 3],
        ["amazon_in", 3],
        ["swiggy", 2],
        ["zomato", 4],
      ],
    );
    await api.approveChange(offline.id);
    await vi.runAllTimersAsync();
    expect(
      (await api.getPlan(plan.id)).steps.find((step) => step.id === offline.id)
        ?.status,
    ).toBe("awaiting_user");
  });

  it("keeps migrated college accounts exposed through Gmail until its recovery number is fixed", async () => {
    const api = createMockApi();
    const takeover = await api.createScenario({
      kind: "takeover",
      root_ids: ["phone_old"],
    });
    const lockout = await api.createScenario({
      kind: "lockout",
      root_ids: ["email_college"],
    });
    const college = await api.createPlan({
      old_root: "email_college",
      new_root: "email_primary",
    });
    const phone = await api.createPlan({
      old_root: "phone_old",
      new_root: "phone_new",
    });
    const figma = college.steps.find((step) => step.account_id === "figma");
    const google = phone.steps.find((step) => step.account_id === "google");
    if (!figma || !google) throw new Error("Missing demo steps");
    await api.approveChange(google.id);
    await api.approveChange(figma.id);
    await vi.runAllTimersAsync();
    expect(
      (await api.getPlan(phone.id)).steps.find((step) => step.id === google.id)
        ?.status,
    ).toBe("awaiting_otp");
    expect(
      (await api.getScenario(lockout.id)).affected_accounts.map(
        (item) => item.node_id,
      ),
    ).not.toContain("figma");
    expect(
      (await api.getScenario(takeover.id)).affected_accounts.find(
        (item) => item.node_id === "figma",
      ),
    ).toMatchObject({ round: 3 });
    const explanation = await api.explain(takeover.id, "figma");
    expect(explanation.steps.map((step) => [step.from_id, step.to_id])).toEqual(
      [
        ["phone_old", "google"],
        ["google", "email_primary"],
        ["email_primary", "figma"],
      ],
    );
    await api.submitOtp(google.id, "654321");
    await vi.runAllTimersAsync();
    expect(
      (await api.getScenario(takeover.id)).affected_accounts.map(
        (item) => item.node_id,
      ),
    ).not.toContain("figma");
    expect((await api.explain(takeover.id, "figma")).outcome).toBe(
      "not_affected",
    );
  });

  it("offers automatic email replacement and removes only verified college exposure", async () => {
    const api = createMockApi();
    const result = await api.createScenario({
      kind: "lockout",
      root_ids: ["email_college"],
    });
    const plan = await api.createPlan({
      old_root: "email_college",
      new_root: "email_primary",
    });
    const figma = plan.steps.find((step) => step.account_id === "figma");
    if (!figma) throw new Error("Missing Figma step");
    expect(figma.tier).toBe(1);
    await api.approveChange(figma.id);
    await vi.runAllTimersAsync();
    expect((await api.getScenario(result.id)).direct_accounts).toEqual([
      "canva",
      "coursera",
      "microsoft",
    ]);
  });
});

describe("REST and SSE boundary", () => {
  it("sends selected inbox root IDs when starting discovery and preserves the default request", async () => {
    const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ started: true }) });
    vi.stubGlobal("fetch", request);
    const api = createRestApi("");
    await api.runIngest(["email:reader@example.test"]);
    expect(request).toHaveBeenLastCalledWith("/api/ingest/run", expect.objectContaining({
      method: "POST",
      body: '{"inboxes":["email:reader@example.test"]}',
    }));
    await api.runIngest();
    expect(request).toHaveBeenLastCalledWith("/api/ingest/run", expect.objectContaining({ method: "POST", body: "{}" }));
  });

  it("uses root_ids and parses the backend response", async () => {
    const request = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          id: "s",
          kind: "takeover",
          root_ids: ["phone_old"],
          actor: "stranger",
          rounds: 0,
          affected_accounts: [],
          direct_accounts: [],
          unknown_accounts: [],
          total_accounts: 17,
          ms: 2,
        }),
      });
    vi.stubGlobal("fetch", request);
    await createRestApi("http://localhost:8000").createScenario({
      kind: "takeover",
      root_ids: ["phone_old"],
    });
    expect(request).toHaveBeenCalledWith(
      "http://localhost:8000/api/scenarios",
      expect.objectContaining({
        method: "POST",
        body: '{"kind":"takeover","root_ids":["phone_old"]}',
      }),
    );
  });

  it("does not surface backend error bodies containing secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 422,
          json: async () => ({ app_password: "secret-value" }),
        }),
    );
    await expect(
      createRestApi().onboard({
        inboxes: [
          {
            host: "imap.example.com",
            username: "demo@example.com",
            app_password: "secret-value",
          },
        ],
        phones: [],
      }),
    ).rejects.toThrow("API request failed (422)");
  });

  it("validates SSE payloads and applies contract defaults", () => {
    const root = rootSchema.parse({
      id: "phone",
      kind: "phone",
      label: "Phone",
    });
    expect(root).toMatchObject({
      status: "active",
      confirmed: true,
      drop_at: null,
    });
    const event = graphEventSchema.parse({
      type: "graph",
      uid: "demo",
      at: "2026-10-17T10:00:00Z",
      data: { nodes: 22, edges: 21, last_query_ms: 3 },
    });
    expect(decodeEvent(event)).toEqual({
      kind: "stats",
      data: { nodes: 22, edges: 21, last_query_ms: 3 },
    });
    expect(() => decodeEvent({ ...event, type: "scenario" })).toThrow();
  });
});


describe("live integration additions", () => {
  it("uses relative /api once and accepts actual string tool calls", async () => {
    const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({text: "Under the methods we model.", buttons: [{label: "Plan", action: "plan_root", payload: {root_id: "phone_old"}}], tool_calls: ["resolve", "takeover_if_reassigned"]})});
    vi.stubGlobal("fetch", fetch);
    const reply = await createRestApi("/api").chat("show risk for 4321");
    expect(fetch).toHaveBeenCalledWith("/api/chat", expect.objectContaining({body: '{"text":"show risk for 4321"}'}));
    expect(reply.tool_calls).toEqual(["resolve", "takeover_if_reassigned"]);
  });

  it("reloads current state on SSE reconnect and closes its subscription", () => {
    class Stream extends EventTarget {
      onmessage = null;
      onerror = null;
      onopen: (() => void) | null = null;
      close = vi.fn();
      constructor(public url: string) { super(); streams.push(this); }
    }
    const streams: Stream[] = [];
    vi.stubGlobal("EventSource", Stream);
    const reconnect = vi.fn();
    const receive = vi.fn();
    const close = createRestApi("/api").subscribe(receive, undefined, reconnect);
    const stream = streams[0];
    expect(stream.url).toBe("/api/events");
    stream.onopen?.();
    expect(reconnect).not.toHaveBeenCalled();
    stream.onopen?.();
    expect(reconnect).toHaveBeenCalledOnce();
    stream.dispatchEvent(new MessageEvent("trace", {data: JSON.stringify({type: "trace", uid: "demo", at: "2026-10-17T10:00:00Z", data: {id: "t:0", at: "2026-10-17T10:00:00Z", tool: "explain", args: {}, query_name: "explain", ms: 1.5, rows: 4, outcome: "path"}})}));
    expect(receive).toHaveBeenCalledWith(expect.objectContaining({kind: "trace", data: expect.objectContaining({query_name: "explain", rows: 4})}));
    close();
    expect(stream.close).toHaveBeenCalledOnce();
  });
});
