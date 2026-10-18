import {
  changeSchema,
  planSchema,
  scenarioRequestSchema,
  planRequestSchema,
  onboardingRequestSchema,
  type LapseApi,
  type UiEvent,
  type ScenarioRequest,
  type ScenarioResult,
  type Reached,
  type PathStep,
  type Plan,
  type Change,
  type ExecStep,
  type ToolCallRecord,
  type AgentScreen,
} from "./contracts";
import {
  accounts,
  roots,
  initialGraph,
  directIds,
  collegeIds,
  evidence,
  label,
} from "./fixtures";

const changeTiers: Record<string, Change["tier"]> = {
  google: 2,
  x: 3,
  amazon_in: 3,
  swiggy: 2,
  zomato: 4,
  figma: 1,
  canva: 1,
  coursera: 1,
  microsoft: 3,
};
const now = () => new Date().toISOString();
const clone = <T>(value: T): T => structuredClone(value);
const settings: Record<string, string> = {
  google: "https://myaccount.google.com/security",
  x: "https://x.com/settings/account",
  amazon_in: "https://www.amazon.in/a/c/your-account",
  swiggy: "https://www.swiggy.com/my-account",
  zomato: "https://www.zomato.com/",
  figma: "https://www.figma.com/settings",
  canva: "https://www.canva.com/settings",
  coursera: "https://www.coursera.org/account-settings",
  microsoft: "https://account.microsoft.com/security",
};
const mockScreen = (caption: string): AgentScreen => ({
  mock: true,
  caption,
  url: `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="560" viewBox="0 0 1000 560"><rect width="1000" height="560" fill="#182425"/><rect x="80" y="70" width="840" height="420" rx="16" fill="#233638"/><g font-family="sans-serif" fill="#d8e9e4"><text x="120" y="130" font-size="18" fill="#a8c8b8">SIMULATED EXECUTOR · DEMO</text><text x="120" y="200" font-size="32">Account recovery settings</text><text x="120" y="255" font-size="20">Recovery number</text><rect x="120" y="275" width="760" height="65" rx="8" fill="#172727"/><text x="145" y="317" font-size="24">••7788 (Jio)</text><rect x="120" y="380" width="210" height="55" rx="8" fill="#a4d5b5"/><text x="146" y="416" font-size="20" fill="#173526">Confirm change</text><text x="380" y="416" font-size="18" fill="#adc2bc">Waiting for approval / verification</text></g></svg>')}`,
});

export function createMockApi(): LapseApi {
  const listeners = new Set<(event: UiEvent) => void>();
  const graph = clone(initialGraph);
  const scenarios = new Map<string, ScenarioResult>();
  const plans = new Map<string, Plan>();
  const traces: ToolCallRecord[] = [];
  const fixed = new Set<string>();
  let serial = 0;
  let screen = mockScreen(
    "Demo executor preview. No account has been changed.",
  );
  let ingestRunning = false;
  const emit = (event: UiEvent) =>
    listeners.forEach((listener) => listener(clone(event)));
  const later = (delay: number, callback: () => void) =>
    setTimeout(callback, delay);
  const singleFactor = (id: string) =>
    graph.edges
      .filter(
        (edge) =>
          edge.source === id && edge.confirmed && !edge.label.includes(" AND "),
      )
      .map((edge) => edge.target);
  const reach = (id: string) => {
    const seen = new Set<string>();
    const queue = [id];
    while (queue.length)
      for (const next of singleFactor(queue.shift()!))
        if (next !== id && !seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
    return seen;
  };
  const stats = () => ({
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    last_query_ms: traces.at(-1)?.ms ?? 2.8,
  });
  const trace = (
    tool: string,
    query: string,
    args: Record<string, unknown>,
    rows: number,
  ) => {
    const record: ToolCallRecord = {
      id: `trace-${++serial}`,
      at: now(),
      tool,
      args,
      query_name: query,
      ms: 2.4 + rows * 0.37,
      rows,
      outcome: "ok",
    };
    traces.push(record);
    emit({ kind: "trace", data: record });
  };
  const reached = (nodeId: string, round: number): Reached => ({
    node_id: nodeId,
    label: label(nodeId),
    node_type: nodeId === "email_primary" ? "Root" : "Account",
    round,
    via_method:
      graph.edges.find((edge) => edge.target === nodeId)?.method_id ?? null,
  });
  function calculate(input: ScenarioRequest, id: string): ScenarioResult {
    let affected: Reached[] = [];
    let direct: string[] = [];
    const hasOld = input.root_ids.includes("phone_old");
    const hasCollege = input.root_ids.includes("email_college");
    if (input.kind === "takeover") {
      if (hasOld) {
        direct = directIds.filter(
          (accountId) => !fixed.has(`phone_old:${accountId}`),
        );
        affected = direct.map((accountId) => reached(accountId, 1));
      }
      if (
        input.root_ids.includes("email_primary") ||
        direct.includes("google")
      ) {
        if (!input.root_ids.includes("email_primary"))
          affected.push(reached("email_primary", 2));
        const next = graph.edges
          .filter(
            (edge) =>
              edge.source === "email_primary" &&
              edge.target !== "github" &&
              (edge.target !== "dropbox" || hasOld),
          )
          .map((edge) => edge.target);
        affected.push(
          ...next.map((accountId) =>
            reached(
              accountId,
              input.root_ids.includes("email_primary") ? 1 : 3,
            ),
          ),
        );
        if (input.root_ids.includes("email_primary")) direct.push(...next);
        if (input.root_ids.includes("device_phone"))
          affected.push(reached("github", 3));
      }
      if (hasCollege) {
        const ids = collegeIds.filter(
          (accountId) => !fixed.has(`email_college:${accountId}`),
        );
        affected.push(...ids.map((accountId) => reached(accountId, 1)));
        direct.push(...ids);
      }
    } else if (hasCollege) {
      direct = collegeIds.filter(
        (accountId) => !fixed.has(`email_college:${accountId}`),
      );
      affected = direct.map((accountId) => ({
        ...reached(accountId, 1),
        via_method: `${accountId}:college_email_signin`,
      }));
    }
    return {
      id,
      kind: input.kind,
      root_ids: input.root_ids,
      actor: input.kind === "takeover" ? "stranger" : "user",
      rounds: Math.max(0, ...affected.map((item) => item.round)),
      affected_accounts: affected,
      direct_accounts: direct,
      unknown_accounts: hasOld ? ["splitwise"] : [],
      total_accounts: accounts.length,
      ms: 8.7,
    };
  }
  function requireScenario(id: string): ScenarioResult {
    const scenario = scenarios.get(id);
    if (!scenario)
      throw new Error("Scenario not found. Run the scenario again.");
    return scenario;
  }
  function requirePlan(id: string): Plan {
    const plan = plans.get(id);
    if (!plan) throw new Error("Plan not found. Create a plan first.");
    return plan;
  }
  function findChange(id: string): { plan: Plan; change: Change } {
    for (const plan of plans.values()) {
      const change = plan.steps.find((item) => item.id === id);
      if (change) return { plan, change };
    }
    throw new Error("Change not found.");
  }
  function stepEvent(change: Change, kind: ExecStep["kind"], message: string) {
    const data: ExecStep = {
      change_id: change.id,
      kind,
      message,
      channel: kind === "need_otp" ? "sms:••7788" : null,
      url:
        kind === "need_user"
          ? change.settings_url
          : kind === "screenshot"
            ? screen.url
            : null,
      at: now(),
    };
    emit({ kind: "exec", data });
  }
  function setStatus(plan: Plan, change: Change, status: Change["status"]) {
    change.status = status;
    emit({ kind: "plan", data: plan });
  }
  function finish(plan: Plan, change: Change) {
    fixed.add(`${change.from_root}:${change.account_id}`);
    const sourceEdge = graph.edges.find(
      (item) =>
        item.source === change.from_root && item.target === change.account_id,
    );
    if (sourceEdge && change.to_root) {
      sourceEdge.source = change.to_root;
      sourceEdge.confirmed = true;
      sourceEdge.label = "Verified replacement";
    }
    setStatus(plan, change, "done");
    stepEvent(
      change,
      "done",
      "Demo: replacement verified. The graph has been updated.",
    );
    trace(
      "verify_change",
      "record_verified_change",
      { change_id: change.id },
      1,
    );
    for (const [id, scenario] of scenarios) {
      const updated = calculate(scenario, id);
      scenarios.set(id, updated);
      emit({ kind: "scenario", data: updated });
    }
    plan.exposure_after = calculate(
      { kind: plan.kind, root_ids: [plan.old_root] },
      "plan-preview",
    ).affected_accounts.filter((item) => item.node_type === "Account").length;
    emit({ kind: "plan", data: plan });
    emit({ kind: "stats", data: stats() });
  }
  function path(
    from: string,
    to: string,
    method: string,
    round: number,
  ): PathStep {
    return {
      from_id: from,
      from_label: label(from),
      to_id: to,
      to_label: label(to),
      method_id:
        graph.edges.find((edge) => edge.source === from && edge.target === to)
          ?.method_id ?? `${to}:${method.toLowerCase().replaceAll(" ", "_")}`,
      method_label: method,
      round,
      evidence: to === "email_primary" ? [] : [evidence(to)],
    };
  }
  trace("load_graph", "graph_snapshot", {}, graph.nodes.length);
  return {
    getRoots: async () => clone(roots),
    getGraph: async () => clone(graph),
    createScenario: async (input) => {
      const parsed = scenarioRequestSchema.parse(input);
      const result = calculate(parsed, `scenario-${++serial}`);
      scenarios.set(result.id, result);
      for (let round = 1; round <= Math.max(1, result.rounds); round++) {
        const currentRound = round;
        later(currentRound * 420, () => {
          const current = requireScenario(result.id);
          const partial = {
            ...current,
            affected_accounts: current.affected_accounts.filter(
              (item) => item.round <= currentRound,
            ),
          };
          emit({ kind: "scenario", data: partial });
          trace(
            "run_scenario",
            "closure_round",
            { scenario_id: result.id, round: currentRound, kind: parsed.kind },
            partial.affected_accounts.length,
          );
        });
      }
      return clone(result);
    },
    getScenario: async (id) => clone(requireScenario(id)),
    explain: async (scenarioId, accountId) => {
      const scenario = requireScenario(scenarioId);
      if (!accounts.some((item) => item.id === accountId))
        return {
          scenario_id: scenarioId,
          account_id: accountId,
          outcome: "not_in_graph",
          steps: [],
        };
      if (
        !scenario.affected_accounts.some((item) => item.node_id === accountId)
      )
        return {
          scenario_id: scenarioId,
          account_id: accountId,
          outcome: "not_affected",
          steps: [],
        };
      let steps: PathStep[];
      if (
        collegeIds.includes(accountId) &&
        graph.edges.some(
          (edge) =>
            edge.source === "email_college" && edge.target === accountId,
        )
      )
        steps = [
          path(
            "email_college",
            accountId,
            scenario.kind === "lockout"
              ? "Only sign-in mailbox closes"
              : "Email reset",
            1,
          ),
        ];
      else if (directIds.includes(accountId))
        steps = [path("phone_old", accountId, "SMS recovery", 1)];
      else {
        steps = scenario.root_ids.includes("email_primary")
          ? []
          : [
              path("phone_old", "google", "SMS recovery", 1),
              path("google", "email_primary", "Controls hosted mailbox", 2),
            ];
        steps.push(
          path(
            "email_primary",
            accountId,
            accountId === "dropbox"
              ? "Email reset AND SMS code"
              : "Email reset",
            3,
          ),
        );
        if (accountId === "dropbox")
          steps.push(
            path("phone_old", accountId, "SMS code AND email reset", 3),
          );
        if (accountId === "github")
          steps.push(
            path("device_phone", accountId, "TOTP AND email reset", 3),
          );
      }
      trace(
        "explain",
        "derivation_path",
        { scenario_id: scenarioId, account_id: accountId },
        steps.length,
      );
      return {
        scenario_id: scenarioId,
        account_id: accountId,
        outcome: "path",
        steps,
      };
    },
    createPlan: async (input) => {
      const request = planRequestSchema.parse(input);
      const college = request.old_root === "email_college";
      const id = `plan-${++serial}`;
      const ids = college ? collegeIds : directIds;
      const steps = ids
        .filter((accountId) => !fixed.has(`${request.old_root}:${accountId}`))
        .map((accountId, index) =>
          changeSchema.parse({
            id: `${id}:${accountId}`,
            plan_id: id,
            order: index + 1,
            account_id: accountId,
            account_label: label(accountId),
            role: college ? "login_email" : "recovery_phone",
            from_root: request.old_root,
            to_root:
              request.new_root ?? (college ? "email_primary" : "phone_new"),
            tier: changeTiers[accountId] ?? 3,
            requires_old_root: true,
            due: request.deadline ?? (college ? "2026-11-15" : "2026-10-31"),
            exposure_removed: accountId === "google" ? 6 : 1,
            settings_url: settings[accountId] ?? null,
            note:
              accountId === "google"
                ? "Move the Gmail recovery number first: it protects the mailbox and five downstream accounts."
                : "Demo procedure. Service capabilities must be verified by the backend policy.",
          }),
        );
      const count = calculate(
        {
          kind: college ? "lockout" : "takeover",
          root_ids: [request.old_root],
        },
        "preview",
      ).affected_accounts.filter((item) => item.node_type === "Account").length;
      const plan = planSchema.parse({
        id,
        kind: college ? "lockout" : "takeover",
        old_root: request.old_root,
        new_root: request.new_root ?? (college ? "email_primary" : "phone_new"),
        deadline: request.deadline ?? (college ? "2026-11-15" : "2026-10-31"),
        feasible: true,
        exposure_before: count,
        exposure_after: count,
        steps,
        created_at: now(),
      });
      plans.set(id, plan);
      trace(
        "plan_changes",
        "rank_changes",
        { old_root: request.old_root },
        steps.length,
      );
      return clone(plan);
    },
    getPlans: async () => clone([...plans.values()]),
    chat: async () => ({ text: "Offline demo. Explore the account map or build a fix plan. Live chat requires the API.", buttons: [{label: "Open account map", action: "open_web", payload: {path: "/graph"}}], tool_calls: [] }),
    getPlan: async (id) => clone(requirePlan(id)),
    approveChange: async (id) => {
      const { plan, change } = findChange(id);
      if (change.status !== "proposed") return clone(change);
      setStatus(plan, change, "approved");
      later(250, () => {
        setStatus(plan, change, "running");
        screen = mockScreen(
          `Demo: preparing ${change.account_label} recovery settings.`,
        );
        stepEvent(change, "screenshot", screen.caption);
        trace(
          "execute_change",
          "change_requirements",
          { change_id: id, tier: change.tier },
          1,
        );
        later(650, () => {
          if (change.tier === 1) finish(plan, change);
          else if (change.tier === 2) {
            setStatus(plan, change, "awaiting_otp");
            stepEvent(
              change,
              "need_otp",
              "Demo: enter any six digits to simulate the new-number verification.",
            );
          } else {
            setStatus(plan, change, "awaiting_user");
            stepEvent(
              change,
              "need_user",
              change.tier === 4
                ? "This step needs an in-person visit. It stays pending until evidence confirms the change."
                : "Open account settings. Demo verification will arrive in a few seconds.",
            );
            if (change.tier === 3) later(6000, () => finish(plan, change));
          }
        });
      });
      return clone(change);
    },
    submitOtp: async (id, code) => {
      const { plan, change } = findChange(id);
      if (change.status !== "awaiting_otp")
        throw new Error("This step is not waiting for a code.");
      if (!/^\d{6}$/.test(code))
        throw new Error("Enter a six-digit verification code.");
      setStatus(plan, change, "running");
      later(650, () => finish(plan, change));
      return clone(change);
    },
    getTrace: async (since) =>
      clone(traces.filter((item) => !since || item.at > since)),
    getScreen: async () => clone(screen),
    getStats: async () => stats(),
    getKeystones: async () => {
      const ranked = graph.nodes
        .map((node) => {
          const downstream = reach(node.id);
          const upstream = graph.nodes.filter((other) =>
            reach(other.id).has(node.id),
          ).length;
          return { node, downstream, score: upstream * downstream.size };
        })
        .filter((item) => item.score > 0)
        .sort(
          (a, b) =>
            b.score - a.score ||
            b.downstream.size - a.downstream.size ||
            a.node.id.localeCompare(b.node.id),
        )
        .slice(0, 3);
      return {
        outcome: "keystones" as const,
        algorithm: "betweenness",
        keystones: ranked.map(({ node, downstream, score }) => ({
          id: node.id,
          label: node.label,
          node_type: node.node_type,
          score,
          downstream: [...downstream].filter((id) =>
            graph.nodes.some(
              (item) => item.id === id && item.node_type === "Account",
            ),
          ).length,
          downstream_labels: [...downstream].map(label).sort(),
        })),
      };
    },
    getPath: async (fromId, toId) => {
      const previous = new Map<string, string>([[fromId, fromId]]);
      const queue = [fromId];
      while (queue.length && !previous.has(toId)) {
        const current = queue.shift()!;
        for (const next of singleFactor(current))
          if (!previous.has(next)) {
            previous.set(next, current);
            queue.push(next);
          }
      }
      if (!previous.has(toId) || fromId === toId)
        return {
          outcome: "no_single_route" as const,
          from_id: fromId,
          to_id: toId,
        };
      const ids = [toId];
      while (ids[0] !== fromId) ids.unshift(previous.get(ids[0])!);
      return {
        outcome: "route" as const,
        algorithm: "SPpaths",
        hops: ids.length - 1,
        route: ids.map((id) => ({ id, label: label(id) })),
      };
    },
    onboard: async (input) => {
      if (!onboardingRequestSchema.safeParse(input).success)
        throw new Error("Check the inbox and phone fields.");
      return {
        telegram_code: "LAPSE-DEMO-4821",
        telegram_url: "https://t.me/",
      };
    },
    runIngest: async () => {
      if (ingestRunning) return { started: false };
      ingestRunning = true;
      for (let round = 1; round <= 5; round++) {
        const current = round;
        later(current * 650, () => {
          emit({
            kind: "ingest",
            data: {
              emails_scanned: current * 248,
              accounts_found: Math.min(17, current * 4),
              edges_inferred: Math.min(21, current * 5),
              edges_confirmed: Math.min(20, current * 4),
              status: current === 5 ? "done" : "running",
            },
          });
          trace("ingest", "upsert_evidence", { batch: current }, 248);
          if (current === 5) {
            ingestRunning = false;
            emit({ kind: "stats", data: stats() });
          }
        });
      }
      return { started: true };
    },
    subscribe: (onEvent) => {
      listeners.add(onEvent);
      return () => {
        listeners.delete(onEvent);
      };
    },
  };
}
