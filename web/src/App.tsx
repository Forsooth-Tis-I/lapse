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
import { Onboarding } from "./components/Onboarding";

type Page = "graph" | "plan" | "agent" | "connect";
type Preset = "takeover" | "lockout" | "both";
const navigation = [
  { id: "graph", label: "Account map", icon: GitBranch },
  { id: "plan", label: "Fix plan", icon: CheckCheck },
  { id: "agent", label: "Agent activity", icon: Radio },
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
  const [plans, setPlans] = useState<Plan[]>([]);
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

  const refreshGraph = useCallback(async () => {
    const [nextGraph, nextRoots, nextStats] = await Promise.all([
      api.getGraph(),
      api.getRoots(),
      api.getStats(),
    ]);
    setGraph(nextGraph);
    setRoots(nextRoots);
    setStats(nextStats);
  }, []);

  useEffect(() => {
    let active = true;
    setError("");
    async function load() {
      try {
        const [
          nextGraph,
          nextRoots,
          nextStats,
          nextTrace,
          nextScreen,
          takeover,
          lockout,
        ] = await Promise.all([
          api.getGraph(),
          api.getRoots(),
          api.getStats(),
          api.getTrace(),
          api.getScreen(),
          api.createScenario({ kind: "takeover", root_ids: ["phone_old"] }),
          api.createScenario({ kind: "lockout", root_ids: ["email_college"] }),
        ]);
        if (!active) return;
        setGraph(nextGraph);
        setRoots(nextRoots);
        setStats(nextStats);
        setTrace(nextTrace);
        setScreen(nextScreen);
        setScenarios([takeover, lockout]);
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
            setTrace((previous) => mergeById(previous, event.data).slice(-150));
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
            setPlans((previous) => mergeById(previous, event.data));
            break;
          case "exec":
            setExecution(event.data);
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
            void api
              .getGraph()
              .then((value) => {
                if (active) setGraph(value);
              })
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
    );
    return () => {
      active = false;
      unsubscribe();
    };
  }, [reload, refreshGraph]);

  useEffect(() => {
    document.documentElement.dataset.theme = light ? "light" : "dark";
  }, [light]);
  useEffect(() => {
    setExplanation(null);
    setExplanationError("");
    if (!selected || !selectedResult) {
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
  }, [selected, selectedResult]);

  function changeStep(step: Change) {
    setPlans((previous) =>
      previous.map((plan) =>
        plan.id === step.plan_id
          ? {
              ...plan,
              steps: plan.steps.map((item) =>
                item.id === step.id ? step : item,
              ),
            }
          : plan,
      ),
    );
  }
  async function createPlans() {
    setCreating(true);
    setError("");
    try {
      const values = await Promise.all([
        api.createPlan({
          old_root: "phone_old",
          new_root: "phone_new",
          deadline: "2026-10-31",
        }),
        api.createPlan({
          old_root: "email_college",
          new_root: "email_primary",
          deadline: "2026-11-15",
        }),
      ]);
      setPlans(values);
    } catch {
      setError("Could not build the fix plan. Please try again.");
    } finally {
      setCreating(false);
    }
  }
  const oldPhone = roots.find((root) => root.id === "phone_old");
  const college = roots.find((root) => root.id === "email_college");
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
                  onClick={() => setPage("plan")}
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
                    onPlan={() => setPage("plan")}
                  />
                )}
              </div>
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
              plans={plans}
              onChange={changeStep}
              onCreate={() => void createPlans()}
              creating={creating}
            />
          )}
          {page === "agent" && (
            <AgentPanel
              trace={trace}
              screen={screen}
              stats={stats}
              execution={execution}
            />
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
        <footer className="app-footer">
          <span>LAPSE</span>
          <span>Your access should end on your terms.</span>
          <span>GRAPH HACKS · 2026</span>
        </footer>
      </div>
    </div>
  );
}
