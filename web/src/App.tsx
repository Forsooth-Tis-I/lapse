import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  CircleHelp,
  GitBranch,
  Layers3,
  Moon,
  Radio,
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
  IngestProgress,
  Keystone,
  Plan,
  Root,
  Route,
  ScenarioResult,
} from "./api";
import { AccountGraph } from "./components/AccountGraph";
import { ExplanationPanel } from "./components/ExplanationPanel";
import { PlanBoard } from "./components/PlanBoard";
import { AgentPanel } from "./components/AgentPanel";
import { Onboarding } from "./components/Onboarding";
import { LockoutSummary } from "./components/LockoutSummary";

type Page = "graph" | "plan" | "agent" | "connect";
type Mode = "takeover" | "lockout";
type Selection = { target: string | null; mode: Mode };
type Assessment = Selection & {
  graph: GraphData;
  status: "pending" | "success" | "error";
};
const navigation = [
  { id: "graph", label: "Account map", icon: GitBranch },
  { id: "plan", label: "Fix plan", icon: CheckCheck },
  { id: "agent", label: "Agent activity", icon: Radio },
  { id: "connect", label: "Connections", icon: Unplug },
] satisfies { id: Page; label: string; icon: typeof GitBranch }[];
const modeOptions = [
  { id: "takeover", label: "Someone else gets it" },
  { id: "lockout", label: "I lose it" },
] satisfies { id: Mode; label: string }[];

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

export function reconcileSelection(
  roots: Root[],
  previous: Selection,
  linked?: ScenarioResult | null,
): Selection {
  if (linked && roots.some((root) => root.id === linked.root_ids[0]))
    return { target: linked.root_ids[0], mode: linked.kind };
  if (roots.some((root) => root.id === previous.target)) return previous;
  const first = rootScenarios(roots)[0];
  const root = roots[0];
  return {
    target: first?.root_ids[0] ?? root?.id ?? null,
    mode: first?.kind ?? (root?.kind === "phone" ? "takeover" : "lockout"),
  };
}

export default function App() {
  const [page, setPage] = useState<Page>(() =>
    ["/onboarding", "/connect"].includes(window.location.pathname)
      ? "connect"
      : "graph",
  );
  const [light, setLight] = useState(() => {
    try {
      return window.localStorage.getItem("lapse-theme") !== "dark";
    } catch {
      return true;
    }
  });
  const [selection, setSelection] = useState<Selection>({
    mode: "takeover",
    target: null,
  });
  const { mode, target } = selection;
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const linkedSelectionApplied = useRef(false);
  const [depth, setDepth] = useState<"direct" | "full">("direct");
  const [keystones, setKeystones] = useState<Keystone[]>([]);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [roots, setRoots] = useState<Root[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioResult[]>([]);
  const scenariosRef = useRef(scenarios);
  scenariosRef.current = scenarios;
  const planRevision = useRef(0);
  const graphRevision = useRef(0);
  const [planRoot, setPlanRoot] = useState<string | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
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
  const [route, setRoute] = useState<Route | null>(null);
  const [creating, setCreating] = useState(false);
  const scenarioStatus =
    !graph || !target
      ? "unassessed"
      : assessment?.graph === graph &&
          assessment.target === target &&
          assessment.mode === mode
        ? assessment.status
        : "pending";
  const results =
    scenarioStatus === "success"
      ? scenarios.filter(
          (result) => result.kind === mode && result.root_ids[0] === target,
        )
      : [];
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
  const topKeystone = keystones[0];
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
    const [nextGraph, nextRoots] = await Promise.all([
      api.getGraph(),
      api.getRoots(),
    ]);
    if (revision !== graphRevision.current) return;
    setGraph(nextGraph);
    setRoots(nextRoots);
    setSelection((previous) => reconcileSelection(nextRoots, previous));
  }, []);

  useEffect(() => {
    if (!graph) return;
    let active = true;
    api
      .getKeystones()
      .then((value) => active && setKeystones(value.keystones))
      .catch(() => active && setKeystones([]));
    return () => {
      active = false;
    };
  }, [graph]);

  useEffect(() => {
    let active = true;
    setError("");
    async function load() {
      const revision = ++graphRevision.current;
      try {
        const [nextGraph, nextRoots, , nextScreen] = await Promise.all([
          api.getGraph(), api.getRoots(), refreshPlans(), api.getScreen(),
        ]);
        if (!active || revision !== graphRevision.current) return;
        const linkedId = new URLSearchParams(window.location.search).get("scenario");
        const linked = linkedId && !linkedSelectionApplied.current
          ? await api.getScenario(linkedId).catch(() => null)
          : null;
        if (!active || revision !== graphRevision.current) return;
        setSelection((previous) => reconcileSelection(nextRoots, previous, linked));
        if (linked && nextRoots.some((root) => root.id === linked.root_ids[0])) setDepth("full");
        linkedSelectionApplied.current = true;
        setGraph(nextGraph);
        setRoots(nextRoots);
        setScreen(nextScreen);
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
    if (!graph || !target) return;
    let active = true;
    const current = { graph, target, mode };
    setAssessment({ ...current, status: "pending" });
    api
      .createScenario({ kind: mode, root_ids: [target] })
      .then((result) => {
        if (active) {
          setScenarios([result]);
          setAssessment({ ...current, status: "success" });
        }
      })
      .catch(() => {
        if (active) setAssessment({ ...current, status: "error" });
      });
    return () => {
      active = false;
    };
  }, [graph, target, mode]);

  useEffect(() => {
    document.documentElement.dataset.theme = light ? "light" : "dark";
    try {
      window.localStorage.setItem("lapse-theme", light ? "light" : "dark");
    } catch {
      // storage unavailable; theme still applies for this session
    }
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
    setRoute(null);
    const rootId = selectedResult.root_ids[0];
    if (rootId)
      void api
        .getPath(rootId, selected)
        .then((value) => active && setRoute(value))
        .catch(() => active && setRoute(null));
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
      if (rootIds[0]) setPlanRoot(rootIds[0]);
      setPage("plan");
    } catch {
      setError("Could not build the fix plan. Please try again.");
    } finally {
      setCreating(false);
    }
  }
  const oldPhone = roots.find((root) => root.kind === "phone" && ["retiring", "inactive"].includes(root.status));
  const targetRoot = roots.find((root) => root.id === target);
  const targetLabel = targetRoot
    ? targetRoot.kind === "email"
      ? `your ${targetRoot.label} inbox`
      : targetRoot.kind === "phone"
        ? `your number ${targetRoot.label}`
        : targetRoot.label
    : "a number or inbox";
  function chooseTarget(id: string | null) {
    setSelection((previous) => ({ ...previous, target: id }));
    setSelected(null);
  }
  const college = roots.find((root) => root.kind === "email" && ["closing", "closed"].includes(root.status));
  const activePlanRoot =
    planRoot ??
    oldPhone?.id ??
    college?.id ??
    currentPlans(plans)[0]?.old_root ??
    roots[0]?.id ??
    null;
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
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item active" : "nav-item"}
              onClick={() => setPage(item.id)}
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
                    {mode === "lockout"
                      ? `If you lose ${targetLabel}.`
                      : `If someone else gets ${targetLabel}.`}
                  </h1>
                  <p>
                    Click any number or inbox on the map to see what it reaches.
                  </p>
                </div>
                <button
                  className="primary-button"
                  onClick={() => target && void createPlans([target])}
                  disabled={creating || results.length === 0 || !targetRoot || targetRoot.status === "active"}
                  title={targetRoot?.status === "active" ? "Plans are for numbers and inboxes you are giving up." : undefined}
                >
                  Plan the fix <ArrowUpRight size={17} />
                </button>
              </div>
              <div className="summary-strip">
                <div className="reach-summary">
                  <span className="eyebrow">ACCOUNTS AT RISK</span>
                  {scenarioStatus === "success" ? (
                    <div className="reach-numbers" aria-label={`${directCount} direct, ${fullCount} full chain`}>
                      <strong>{directCount}</strong>
                      <span>direct</span>
                      <ArrowRight size={22} />
                      <strong className="full-count">{fullCount}</strong>
                      <span>full chain</span>
                    </div>
                  ) : (
                    <p role="status">
                      {scenarioStatus === "pending" ? "Checking risk…"
                        : scenarioStatus === "error" ? "Risk check unavailable"
                        : "Choose a number or inbox to assess risk."}
                    </p>
                  )}
                </div>
                <div className="unknown-summary">
                  <CircleHelp size={18} />
                  <div>
                    <strong>{scenarioStatus === "success" ? unknownCount : "—"} unknown</strong>
                    <span>Not modelled. Not safe.</span>
                  </div>
                </div>
                <div className="deadline-summary">
                  <span className="deadline-icon">{oldPhone?.drop_at?.slice(8, 10) ?? "—"}</span>
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
                  <span className="deadline-icon">{college?.closes_at?.slice(8, 10) ?? "—"}</span>
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
                    <label className="target-picker">
                      What if
                      <select
                        aria-label="What if"
                        value={target ?? ""}
                        onChange={(event) => chooseTarget(event.target.value || null)}
                      >
                        {roots.map((root) => (
                          <option key={root.id} value={root.id}>
                            {root.label}
                            {root.status !== "active" ? ` (${root.status})` : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div
                      className="scenario-control"
                      role="group"
                      aria-label="Scenario"
                    >
                      {modeOptions.map((option) => (
                        <button
                          key={option.id}
                          aria-pressed={mode === option.id}
                          onClick={() => {
                            setSelection((previous) => ({ ...previous, mode: option.id }));
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
                  {scenarioStatus === "error" && (
                    <div className="notice" role="alert">
                      Could not run this scenario. No risk conclusion is available.
                      <button className="secondary-button" onClick={() => setReload((value) => value + 1)}>
                        Retry
                      </button>
                    </div>
                  )}
                  {topKeystone && (
                    <p className="keystone-line">
                      <span className="keystone-dot" aria-hidden="true" />
                      Fix first: <strong>{topKeystone.label}</strong> ·{" "}
                      {topKeystone.downstream}{" "}
                      {topKeystone.downstream === 1 ? "account depends" : "accounts depend"} on it
                    </p>
                  )}
                  {graph ? (
                    <AccountGraph
                      graph={graph}
                      results={results}
                      depth={depth}
                      keystoneIds={keystones.map((item) => item.id)}
                      selected={selected}
                      explanation={explanation}
                      onSelect={setSelected}
                      onSelectRoot={chooseTarget}
                      fixedAccountIds={scenarioStatus !== "success" ? [] : plans
                        .filter(
                          (plan) => plan.kind === mode && plan.old_root === target,
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
                    route={route}
                    loading={explaining}
                    error={explanationError}
                    results={results}
                    onClose={() => setSelected(null)}
                  />
                )}
              </div>
              <LockoutSummary results={results} />
            </section>
          )}
          {page === "plan" && (
            <PlanBoard
              plans={currentPlans(plans).filter((plan) => plan.old_root === activePlanRoot)}
              roots={roots}
              accountLabels={Object.fromEntries((graph?.nodes ?? []).map((node) => [node.id, node.label]))}
              selectedRoot={activePlanRoot}
              onSelectRoot={setPlanRoot}
              onCreateRoot={(rootId) => void createPlans([rootId])}
              onChange={changeStep}
              onCreate={() => void createPlans()}
              creating={creating}
            />
          )}
          {page === "agent" && (
            <AgentPanel screen={screen} execution={execution} />
          )}
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
      </div>
    </div>
  );
}
