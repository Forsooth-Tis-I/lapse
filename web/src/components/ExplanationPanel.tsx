import { ArrowDown, Mail, ShieldCheck, X } from "lucide-react";
import type { Explanation, GraphData, Route, ScenarioResult } from "../api";

export function ExplanationPanel({
  selected,
  graph,
  explanation,
  route = null,
  loading,
  error,
  results,
  onClose,
}: {
  selected: string | null;
  graph: GraphData;
  explanation: Explanation | null;
  route?: Route | null;
  loading: boolean;
  error: string;
  results: ScenarioResult[];
  onClose: () => void;
}) {
  const node = graph.nodes.find((n) => n.id === selected);
  const unknown = node?.account?.modelled === false;
  const lockoutOnly =
    results.length > 0 && results.every((result) => result.kind === "lockout");
  const affected = results.find((r) =>
    r.affected_accounts.some((a) => a.node_id === selected),
  );
  const evidence = [
    ...new Map(
      explanation?.steps
        .flatMap((step) => step.evidence)
        .map((item) => [item.id, item]) ?? [],
    ).values(),
  ];
  return (
    <aside className="explanation-panel">
      <div className="panel-title">
        <span>{selected ? "CONNECTION DETAILS" : "READ YOUR MAP"}</span>
        {selected && (
          <button
            className="icon-button"
            aria-label="Close account details"
            onClick={onClose}
          >
            <X size={17} />
          </button>
        )}
      </div>
      {!node ? (
        <div className="explanation-intro">
          <div className="path-symbol">↗</div>
          <h2>
            {lockoutOnly ? (
              <>
                When the inbox goes,
                <br />
                what goes with it?
              </>
            ) : (
              <>
                One number.
                <br />
                More doors than you think.
              </>
            )}
          </h2>
          <p>
            {lockoutOnly
              ? "See which accounts depend on the closing mailbox for fresh sign-in. Losing one recovery route may still leave another way in."
              : "Start with the direct connections. Then follow the chain through Gmail."}
          </p>
          <p>Select an account on the map to see exactly how it can be reached.</p>
        </div>
      ) : (
        <div className="explanation-content">
          <span
            className={`risk-label ${unknown ? "unknown" : affected?.kind || "safe"}`}
          >
            {unknown
              ? "Unknown, not safe"
              : affected?.kind === "takeover"
                ? "Stranger can reach"
                : affected?.kind === "lockout"
                  ? "You would lose access"
                  : "Not affected in this scenario"}
          </span>
          <h2>{node.label}</h2>
          {unknown ? (
            <p><strong>Not in the graph of modelled methods.</strong> We found this account, but its recovery methods are not modelled. Confirm its settings yourself. Unknown, not safe.</p>
          ) : loading ? (
            <p role="status">Reading the derivation…</p>
          ) : error ? (
            <p className="error-text" role="alert">
              {error}
            </p>
          ) : explanation?.outcome === "path" ? (
            <>
              <p className="explanation-subtitle">
                The graph found this path under the methods we model.
              </p>
              {route && (
                <p className="shortest-route">
                  <span className="eyebrow">SHORTEST SINGLE-FACTOR ROUTE</span>
                  {route.outcome === "route"
                    ? `${route.route.map((step) => step.label).join(" → ")} (${route.hops} ${route.hops === 1 ? "hop" : "hops"})`
                    : "None. Reaching this account takes several factors at once."}
                </p>
              )}
              <ol className="path-chain">
                {explanation.steps.map((step, i) => (
                  <li key={`${step.method_id}-${step.from_id}-${i}`}>
                    <div className="path-source">
                      <span className="path-dot" />
                      {step.from_label}
                    </div>
                    <div className="path-method">
                      <ArrowDown size={14} />
                      <span>{step.method_label}</span>
                    </div>
                    <div className="path-target">
                      {step.to_label}
                      <span>ROUND {step.round}</span>
                    </div>
                  </li>
                ))}
              </ol>
              <p className="and-note">
                For an AND method, every listed prerequisite is required. Paths
                show the evidence available to the graph.
              </p>
            </>
          ) : (
            <div className="safe-callout">
              <ShieldCheck size={26} />
              <p>
                {lockoutOnly
                  ? "This account retains a fresh sign-in path under the methods we model."
                  : "No successful takeover path under the methods we model. An AND method fails if the stranger lacks even one required factor."}
              </p>
              <ul className="prerequisite-list">
                {graph.edges
                  .filter((edge) => edge.target === selected)
                  .map((edge) => (
                    <li key={edge.id}>
                      {
                        graph.nodes.find((item) => item.id === edge.source)
                          ?.label
                      }
                      : {edge.label}
                    </li>
                  ))}
              </ul>
              {results.some((r) => r.kind === "lockout") && (
                <p>
                  Losing a recovery route does not always mean losing fresh
                  sign-in access.
                </p>
              )}
            </div>
          )}
          {evidence.length > 0 && (
            <section className="evidence">
              <h3>
                <Mail size={15} /> Evidence emails{" "}
                <span>{evidence.length}</span>
              </h3>
              {evidence.map((item) => (
                <article key={item.id}>
                  <strong>{item.subject}</strong>
                  <span>{item.sender}</span>
                  <time dateTime={item.date}>
                    {new Date(item.date).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </time>
                  <p>{item.snippet}</p>
                </article>
              ))}
            </section>
          )}
        </div>
      )}
    </aside>
  );
}
