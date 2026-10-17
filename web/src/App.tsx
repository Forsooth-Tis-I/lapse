import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  MessageCircle,
  CircleHelp,
  GitBranch,
  Layers3,
  Moon,
  Radio,
  Shield,
  Sun,
  Unplug,
} from "lucide-react";
import { api, isMock } from "./api";
import type {
  AgentScreen,
  Change,
  ExecStep,
  Explanation,
  GraphData,
  GraphStats,
  IngestProgress,
  Plan,
  Root,
  ScenarioResult,
  ToolCallRecord,
} from "./api";
import { AccountGraph } from "./components/AccountGraph";
import { ExplanationPanel } from "./components/ExplanationPanel";
import { PlanBoard } from "./components/PlanBoard";
import { AgentPanel } from "./components/AgentPanel";
import { ChatPanel } from "./components/ChatPanel";
import { Onboarding } from "./components/Onboarding";
import { LockoutSummary } from "./components/LockoutSummary";

type Page = "graph" | "plan" | "agent" | "connect" | "chat";
type Preset = "takeover" | "lockout" | "both";
const navigation = [
  { id: "graph", label: "Account map", icon: GitBranch },
  { id: "plan", label: "Fix plan", icon: CheckCheck },
  { id: "agent", label: "Agent activity", icon: Radio },
  { id: "chat", label: "Chat with Lapse", icon: MessageCircle },
  { id: "connect", label: "Connections", icon: Unplug },
] satisfies { id: Page; label: string; icon: typeof GitBranch }[];
const scenarioOptions = [
  { id: "takeover", label: "Stranger gets ••4321" },
  { id: "lockout", label: "College email closes" },
  { id: "both", label: "Both" },
] satisfies { id: Preset; label: string }[];

function daysUntil(date: string) {
  return Math.ceil((Date.parse(`${date}T00:00:00`) - Date.now()) / 86_400_000);
}
function deadlineLabel(date: string) {
  const days = daysUntil(date);
  return days > 0
    ? `${days} days left`
    : days === 0
      ? "Today"
      : `${Math.abs(days)} days ago`;
}
function mergeById<T extends { id: string }>(items: T[], item: T) {
  return items.some((existing) => existing.id === item.id)
    ? items.map((existing) => (existing.id === item.id ? item : existing))
    : [...items, item];
}

export function mergeTrace(previous: ToolCallRecord[], incoming: ToolCallRecord[]) {
  return [...new Map([...previous, ...incoming].map((row) => [row.id, row])).values()]
    .sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id)).slice(-150);
}

export function currentPlans(plans: Plan[]) {
  const latest = new Map<string, Plan>();
  for (const plan of [...plans].sort((a, b) => a.created_at.localeCompare(b.created_at))) latest.set(plan.old_root, plan);
  return [...latest.values()];
}
function rootScenarios(roots: Root[]) {
  return roots.filter((root) =>
    (root.kind === "phone" && ["retiring", "inactive"].includes(root.status)) ||
    (root.kind === "email" && ["closing", "closed"].includes(root.status)),
  ).map((root) => ({kind: root.kind === "phone" ? "takeover" as const : "lockout" as const, root_ids: [root.id]}));
}

export default function App() {
  const [page, setPage] = useState<Page>("graph");
  const [light, setLight] = useState(false);
  const [preset, setPreset] = useState<Preset>("takeover");
  const [depth, setDepth] = useState<"direct" | "full">("direct");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [roots, setRoots] = useState<Root[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioResult[]>([]);
  const scenariosRef = useRef(scenarios);
  scenariosRef.current = scenarios;
  const planRevision = useRef(0);
  const graphRevision = useRef(0);
  const [planSelection, setPlanSelection] = useState<string | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [traceSelection, setTraceSelection] = useState<{tool: string; record?: ToolCallRecord} | null>(null);
  const [trace, setTrace] = useState<ToolCallRecord[]>([]);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [screen, setScreen] = useState<AgentScreen | null>(null);
  const [execution, setExecution] = useState<ExecStep | null>(null);
  const [progress, setProgress] = useState<IngestProgress | null>(null);
  const [error, setError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [explanationError, setExplanationError] = useState("");
  const [explaining, setExplaining] = useState(false);
  const [creating, setCreating] = useState(false);
  const results = scenarios.filter(
    (result) => preset === "both" || result.kind === preset,
  );
  const directCount = new Set(
    results.flatMap((result) => result.direct_accounts),
  ).size;
  const fullCount = new Set(
    results.flatMap((result) =>
      result.affected_accounts
        .filter((item) => item.node_type === "Account")
        .map((item) => item.node_id),
    ),
  ).size;
  const unknownCount = new Set(
    results.flatMap((result) => result.unknown_accounts),
  ).size;
  const selectedResult =
    results.find((result) =>
      result.affected_accounts.some((item) => item.node_id === selected),
    ) ?? results[0];

  const refreshPlans = useCallback(async () => {
    const revision = ++planRevision.current;
    const values = await api.getPlans();
    if (revision === planRevision.current) setPlans(values);
  }, []);

  const refreshGraph = useCallback(async () => {
    const revision = ++graphRevision.current;
    const [nextGraph, nextRoots, nextStats] = await Promise.all([
      api.getGraph(),
      api.getRoots(),
      api.getStats(),
    ]);
    const requests = rootScenarios(nextRoots);
    const nextScenarios = await Promise.all(requests.map((request) => api.createScenario(request)));
    if (revision !== graphRevision.current) return;
    setGraph(nextGraph);
    setRoots(nextRoots);
    setStats(nextStats);
    setScenarios(nextScenarios);
  }, []);

  useEffect(() => {
    let active = true;
    setError("");
    async function load() {
      const revision = ++graphRevision.current;
      try {
        const [nextGraph, nextRoots, nextStats, , nextTrace, nextScreen] = await Promise.all([
          api.getGraph(), api.getRoots(), api.getStats(), refreshPlans(), api.getTrace(), api.getScreen(),
        ]);
        const nextScenarios = await Promise.all(rootScenarios(nextRoots).map((request) => api.createScenario(request)));
        if (!active || revision !== graphRevision.current) return;
        setGraph(nextGraph);
        setRoots(nextRoots);
        setStats(nextStats);
        setTrace((previous) => mergeTrace(previous, nextTrace));
        setScreen(nextScreen);
        setScenarios(nextScenarios);
        setStreamError("");
      } catch {
        if (active)
          setError(
            "Could not load Lapse. Check the API connection, then try again.",
          );
      }
    }
    void load();
    const unsubscribe = api.subscribe(
      (event) => {
        if (!active) return;
        setStreamError("");
        switch (event.kind) {
          case "trace":
            setTrace((previous) => mergeTrace(previous, [event.data]));
            break;
          case "scenario": {
            if (
              !scenariosRef.current.some(
                (result) => result.id === event.data.id,
              )
            )
              break;
            void api
              .getScenario(event.data.id)
              .then((result) => {
                if (active)
                  setScenarios((previous) =>
                    previous.map((item) =>
                      item.id === result.id ? result : item,
                    ),
                  );
              })
              .catch(() => setStreamError("Could not refresh the scenario."));
            break;
          }
          case "plan":
            ++planRevision.current;
            setPlans((previous) => mergeById(previous, event.data));
            break;
          case "exec":
            setExecution(event.data);
            void refreshPlans()
              .catch(() => setStreamError("Could not refresh the plan."));
            if (event.data.kind === "screenshot")
              void api
                .getScreen()
                .then((value) => {
                  if (active) setScreen(value);
                })
                .catch(() =>
                  setStreamError("Could not load the executor screenshot."),
                );
            if (event.data.kind === "done")
              void refreshGraph().catch(() =>
                setStreamError("Could not refresh the graph."),
              );
            break;
          case "ingest":
            setProgress(event.data);
            if (event.data.status === "done")
              void refreshGraph().catch(() =>
                setStreamError("Could not refresh the graph."),
              );
            break;
          case "stats":
            setStats(event.data);
            void refreshGraph()
              .catch(() => setStreamError("Could not refresh the graph."));
            break;
          case "other":
            if (event.data.type === "graph")
              void refreshGraph().catch(() =>
                setStreamError("Could not refresh the graph."),
              );
            break;
          case "signal":
            break;
        }
      },
      () => {
        if (active)
          setStreamError("Live connection interrupted. Reconnecting…");
      },
      () => { void load(); },
    );
    return () => {
      active = false;
      ++planRevision.current;
      ++graphRevision.current;
      unsubscribe();
    };
  }, [reload, refreshGraph, refreshPlans]);

  useEffect(() => {
    document.documentElement.dataset.theme = light ? "light" : "dark";
  }, [light]);
  useEffect(() => {
    setExplanation(null);
    setExplanationError("");
    if (!selected || !selectedResult || graph?.nodes.find((node) => node.id === selected)?.account?.modelled === false) {
      setExplaining(false);
      return;
    }
    let active = true;
    setExplaining(true);
    void api
      .explain(selectedResult.id, selected)
      .then((value) => {
        if (active) setExplanation(value);
      })
      .catch(() => {
        if (active)
          setExplanationError(
            "Could not load this path. Select the account again to retry.",
          );
      })
      .finally(() => {
        if (active) setExplaining(false);
      });
    return () => {
      active = false;
    };
  }, [selected, selectedResult, graph]);

  function changeStep(_step: Change) {
    void refreshPlans().catch(() => setError("Could not refresh the plan."));
  }
  async function createPlans(rootIds = [...new Set(results.flatMap((result) => result.root_ids))]) {
    if (creating) return;
    setCreating(true);
    setError("");
    try {
      for (const rootId of rootIds) {
        const root = roots.find((item) => item.id === rootId);
        const replacement = roots.find((item) => item.kind === root?.kind && item.status === "active" && item.id !== rootId);
        const deadline = root?.drop_at ?? root?.closes_at ?? root?.expires_at;
        const existing = currentPlans(plans).find((plan) => plan.old_root === rootId && plan.new_root === (replacement?.id ?? null) && plan.steps.some((step) => !["done", "skipped"].includes(step.status)));
        if (existing) continue;
        const plan = await api.createPlan({
          old_root: rootId,
          ...(replacement ? {new_root: replacement.id} : {}),
          ...(deadline ? {deadline} : {}),
        });
        ++planRevision.current;
        setPlans((previous) => mergeById(previous, plan));
      }
      setPlanSelection(null);
      setPage("plan");
    } catch {
      setError("Could not build the fix plan. Please try again.");
    } finally {
      setCreating(false);
    }
  }
  async function openChatPath(path: string) {
    const url = new URL(path, window.location.origin);
    try {
      if (url.pathname.startsWith("/plans/")) {
        const id = decodeURIComponent(url.pathname.slice(7));
        const revision = planRevision.current;
        const plan = await api.getPlan(id);
        if (revision === planRevision.current) setPlans((previous) => mergeById(previous, plan));
        else await refreshPlans();
        setPlanSelection(id);
        setPage("plan");
      } else if (url.pathname === "/graph") {
        const id = url.searchParams.get("scenario");
        if (id) {
          const scenario = await api.getScenario(id);
          setScenarios((previous) => [...previous.filter((item) => item.kind !== scenario.kind), scenario]);
          setPreset(scenario.kind);
          setDepth("full");
        }
        setPage("graph");
      }
    } catch { setError("Could not open the linked result. Please try again."); }
  }
  const oldPhone = roots.find((root) => root.kind === "phone" && ["retiring", "inactive"].includes(root.status));
  const college = roots.find((root) => root.kind === "email" && ["closing", "closed"].includes(root.status));
  const verified = plans
    .flatMap((plan) => plan.steps)
    .filter((step) => step.status === "done").length;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            setPage("graph");
          }}
          aria-label="Lapse home"
        >
          <span className="brand-symbol">
            <i />
            <i />
            <i />
          </span>
          lapse<span className="brand-period">.</span>
        </a>
        <div className="workspace-label">YOUR ACCESS, ACCOUNTED FOR</div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item active" : "nav-item"}
              onClick={() => { if (item.id === "plan") setPlanSelection(null); setPage(item.id); }}
              aria-current={page === item.id ? "page" : undefined}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "plan" && verified > 0 && (
                <span className="nav-count">{verified}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Shield size={19} />
            <p>
              A little certainty.
              <br />
              Before things change.
            </p>
          </div>
          <div className="profile">
            <span className="avatar">L</span>
            <div>
              <strong>{isMock ? "Demo workspace" : "Your workspace"}</strong>
              <span>{isMock ? "Local simulation" : "Connected to Lapse"}</span>
            </div>
            <span className="dot" />
          </div>
          <button
            className="theme-toggle"
            onClick={() => setLight((value) => !value)}
          >
            {light ? <Moon size={16} /> : <Sun size={16} />}
            {light ? "Dark appearance" : "Light appearance"}
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            WORKSPACE <span>/</span>{" "}
            {navigation.find((item) => item.id === page)?.label}
          </span>
          <div className="flex items-center gap-5">
            <span className="connection-label">
              <span className={`dot ${streamError ? "warning" : ""}`} />
              {streamError
                ? "Reconnecting"
                : isMock
                  ? "Demo data"
                  : "Live connection"}
            </span>
            <span className="topbar-private">
              <Shield size={13} /> Private by design
            </span>
          </div>
        </header>
        <main id="main-content">
          {error && (
            <div className="error-banner" role="alert">
              {error}
              <button onClick={() => setReload((value) => value + 1)}>
                Retry
              </button>
            </div>
          )}
          {streamError && (
            <div className="stream-banner" role="status">
              {streamError}
            </div>
          )}
          {page === "graph" && (
            <section className="graph-page">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">KNOW WHAT YOU COULD LOSE</span>
                  <h1>
                    {preset === "lockout"
                      ? "When an inbox closes."
                      : preset === "both"
                        ? "Two changes. One clear picture."
                        : "An old number. A longer reach."}
                  </h1>
                  <p>
                    {preset === "lockout"
                      ? "See which accounts lose fresh sign-in access when your college email closes."
                      : "Follow the connections that outlast your phone number."}
                  </p>
                </div>
                <button
                  className="primary-button"
                  onClick={() => void createPlans()}
                  disabled={creating || results.length === 0}
                >
                  Plan the fix <ArrowUpRight size={17} />
                </button>
              </div>
              <div className="summary-strip">
                <div className="reach-summary">
                  <span className="eyebrow">ACCOUNTS AT RISK</span>
                  <div className="reach-numbers">
                    <strong>{directCount}</strong>
                    <span>direct</span>
                    <ArrowRight size={22} />
                    <strong className="full-count">{fullCount}</strong>
                    <span>full chain</span>
                  </div>
                </div>
                <div className="unknown-summary">
                  <CircleHelp size={18} />
                  <div>
                    <strong>{unknownCount} unknown</strong>
                    <span>Not modelled. Not safe.</span>
                  </div>
                </div>
                <div className="deadline-summary">
                  <span className="deadline-icon">31</span>
                  <div>
                    <strong>
                      Old SIM ·{" "}
                      {oldPhone?.drop_at
                        ? deadlineLabel(oldPhone.drop_at)
                        : "No deadline"}
                    </strong>
                    <span>
                      Drop {oldPhone?.drop_at ?? "—"} · Reissuable{" "}
                      {oldPhone?.reissue_after ?? "—"}
                    </span>
                  </div>
                </div>
                <div className="deadline-summary college-deadline">
                  <span className="deadline-icon">15</span>
                  <div>
                    <strong>
                      College email ·{" "}
                      {college?.closes_at
                        ? deadlineLabel(college.closes_at)
                        : "No deadline"}
                    </strong>
                    <span>Closes {college?.closes_at ?? "—"}</span>
                  </div>
                </div>
              </div>
              <div className="map-workspace">
                <div className="map-main">
                  <div className="map-toolbar">
                    <div
                      className="scenario-control"
                      role="group"
                      aria-label="Scenario"
                    >
                      {scenarioOptions.map((option) => (
                        <button
                          key={option.id}
                          aria-pressed={preset === option.id}
                          onClick={() => {
                            setPreset(option.id);
                            setSelected(null);
                          }}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    <div
                      className="depth-control"
                      role="group"
                      aria-label="Depth"
                    >
                      <button
                        aria-pressed={depth === "direct"}
                        onClick={() => setDepth("direct")}
                      >
                        Direct only
                      </button>
                      <button
                        aria-pressed={depth === "full"}
                        onClick={() => setDepth("full")}
                      >
                        <Layers3 size={14} />
                        Full chain
                      </button>
                    </div>
                  </div>
                  <div className="map-context">
                    <span>
                      <span className="dot danger" />
                      {depth === "direct" ? directCount : fullCount} affected
                      account
                      {(depth === "direct" ? directCount : fullCount) === 1
                        ? ""
                        : "s"}
                    </span>
                    <span>
                      {preset === "lockout"
                        ? "USER LOSES ROOT"
                        : preset === "both"
                          ? "TAKEOVER + LOCKOUT"
                          : "STRANGER GAINS ROOT"}{" "}
                      · UNDER THE METHODS WE MODEL
                    </span>
                  </div>
                  {graph ? (
                    <AccountGraph
                      graph={graph}
                      results={results}
                      depth={depth}
                      selected={selected}
                      explanation={explanation}
                      onSelect={setSelected}
                      fixedAccountIds={plans
                        .filter(
                          (plan) => preset === "both" || plan.kind === preset,
                        )
                        .flatMap((plan) =>
                          plan.steps
                            .filter((step) => step.status === "done")
                            .map((step) => step.account_id),
                        )}
                    />
                  ) : (
                    <div className="loading-map" role="status">
                      Loading your account map…
                    </div>
                  )}
                  <div className="map-footer">
                    <div className="legend">
                      <span>
                        <i className="red" />
                        Stranger can reach
                      </span>
                      <span>
                        <i className="amber" />
                        You lose access
                      </span>
                      <span>
                        <i className="green" />
                        Not affected / fixed
                      </span>
                      <span>
                        <i className="dashed" />
                        Unconfirmed
                      </span>
                      <span>
                        <i className="outline" />
                        Unknown
                      </span>
                    </div>
                    <label className="account-picker">
                      Inspect
                      <select
                        aria-label="Inspect account"
                        value={selected || ""}
                        onChange={(event) =>
                          setSelected(event.target.value || null)
                        }
                      >
                        <option value="">Choose account</option>
                        {graph?.nodes
                          .filter((node) => node.node_type === "Account")
                          .map((node) => (
                            <option key={node.id} value={node.id}>
                              {node.label}
                            </option>
                          ))}
                      </select>
                    </label>
                  </div>
                </div>
                {graph && (
                  <ExplanationPanel
                    selected={selected}
                    graph={graph}
                    explanation={explanation}
                    loading={explaining}
                    error={explanationError}
                    results={results}
                    onClose={() => setSelected(null)}
                    onPlan={() => void createPlans()}
                  />
                )}
              </div>
              <section className="decision-summary" aria-label="How Lapse decided">
                <strong>How Lapse decided</strong>
                <span>Depth 1: {directCount} affected accounts. Full chain: {fullCount}.</span>
                <span>{preset === "takeover"
                  ? "The chain continues through the mailbox recovered by the old phone."
                  : preset === "lockout" ? "Fresh sign-in requires a route that survives the mailbox closing."
                  : "Takeover and fresh sign-in lockout are evaluated separately, then accounts are counted once."}</span>
                <LockoutSummary results={results} />
              </section>
              <div className="graph-bottom">
                <span>
                  <GitBranch size={14} />
                  {stats?.nodes ?? 0} nodes · {stats?.edges ?? 0} connections
                </span>
                <p>
                  {isMock ? "Simulated persona and evidence. " : ""}Reach is
                  derived from recovery methods, not just shared contact
                  details.
                </p>
                <button onClick={() => setPage("agent")}>
                  Inspect agent trace <ArrowUpRight size={14} />
                </button>
              </div>
            </section>
          )}
          {page === "plan" && (
            <PlanBoard
              plans={planSelection ? plans.filter((plan) => plan.id === planSelection) : currentPlans(plans)}
              roots={roots}
              onCreateRoot={(rootId) => void createPlans([rootId])}
              onChange={changeStep}
              onCreate={() => void createPlans()}
              creating={creating}
            />
          )}
          {page === "agent" && (
            <AgentPanel
              trace={trace}
              selectedTool={traceSelection?.tool}
              selectedRecord={traceSelection?.record}
              screen={screen}
              stats={stats}
              execution={execution}
            />
          )}
          <div className="chat-page" hidden={page !== "chat"}>
            <ChatPanel
              onPlanRoot={(rootId) => void createPlans([rootId])}
              onOpenWeb={(path) => void openChatPath(path)}
              onShowTrace={(tool, record) => { setTraceSelection({tool, record}); setPage("agent"); }}
              onReply={async () => {
                try {
                  const rows = await api.getTrace();
                  setTrace((previous) => mergeTrace(previous, rows));
                  return rows;
                } catch {
                  setError("Could not refresh the trace.");
                  return [];
                }
              }}
              onApproveChanges={async (ids) => {
                for (const id of ids) changeStep(await api.approveChange(id));
                await refreshPlans();
              }}
            />
          </div>
          {page === "connect" && (
            <Onboarding
              progress={progress}
              onConnected={() =>
                void refreshGraph().catch(() =>
                  setError("Could not refresh connections."),
                )
              }
            />
          )}
        </main>
        <footer className="app-footer">
          <span>LAPSE</span>
          <span>Your access should end on your terms.</span>
          <span>GRAPH HACKS · 2026</span>
        </footer>
      </div>
    </div>
  );
}
