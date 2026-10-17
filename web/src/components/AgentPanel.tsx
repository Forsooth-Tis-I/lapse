import { useEffect, useRef } from "react";
import { Camera, Database, Terminal } from "lucide-react";
import type { AgentScreen, ExecStep, GraphStats, ToolCallRecord } from "../api";

export function AgentPanel({
  trace,
  screen,
  stats,
  execution,
  selectedTool,
  selectedRecord,
}: {
  trace: ToolCallRecord[];
  selectedTool?: string | null;
  selectedRecord?: ToolCallRecord;
  screen: AgentScreen | null;
  stats: GraphStats | null;
  execution: ExecStep | null;
}) {
  const selectedRow = useRef<HTMLTableRowElement>(null);
  const selectedId = selectedRecord?.id ?? [...trace].reverse().find((row) => row.tool === selectedTool)?.id;
  useEffect(() => { selectedRow.current?.scrollIntoView({block: "nearest"}); }, [selectedId]);
  const rows = selectedRecord && !trace.some((row) => row.id === selectedRecord.id) ? [...trace, selectedRecord] : trace;
  return (
    <section className="page-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">THE WORK, IN PLAIN SIGHT</span>
          <h1>Nothing behind the curtain.</h1>
          <p>
            Follow the queries, inspect the evidence, and see what the executor
            sees.
          </p>
        </div>
        <span className="live-label">
          <span className="dot" />
          Live activity
        </span>
      </div>
      <section className="trace-panel">
        <div className="panel-title">
          <span>
            <Terminal size={16} /> Tool trace
          </span>
          <span className="mono">{trace.length} CALLS</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Tool / arguments</th>
                <th>Cypher query name</th>
                <th>ms</th>
                <th>Rows</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((row) => (
                <tr key={row.id} id={`trace-${row.id}`} ref={row.id === selectedId ? selectedRow : undefined} className={row.id === selectedId ? "selected-trace" : ""}>
                  <td className="mono">
                    {new Date(row.at).toLocaleTimeString("en-GB")}
                  </td>
                  <td>
                    <strong>{row.tool}</strong>
                    <code>{JSON.stringify(row.args)}</code>
                  </td>
                  <td>
                    <code>{row.query_name || "—"}</code>
                  </td>
                  <td className="mono">{row.ms.toFixed(1)}</td>
                  <td className="mono">{row.rows}</td>
                  <td>
                    <span className={`trace-outcome ${row.outcome}`}>
                      {row.outcome}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {trace.length === 0 && (
            <p className="empty-trace">
              No tool calls yet. Run a scenario to start the trace.
            </p>
          )}
        </div>
      </section>
      <div className="agent-top">
        <section className="agent-screen">
          <div className="panel-title">
            <span>
              <Camera size={16} /> Agent screen
            </span>
            <span className="mono">
              {screen?.mock ? "SIMULATED EXECUTOR" : "EXECUTOR"}
            </span>
          </div>
          {screen?.url ? (
            <img
              src={screen.url}
              alt={screen.caption || "Latest executor screenshot"}
            />
          ) : (
            <div className="screen-empty">
              <Camera size={32} />
              <h3>No executor screenshot yet</h3>
              <p>The latest browser screenshot will appear here.</p>
            </div>
          )}
          <div className="screen-caption">
            <span className="dot" />
            {execution?.message ||
              screen?.caption ||
              "No actions have been approved."}
          </div>
        </section>
        <section className="graph-stats">
          <Database size={24} />
          <span className="eyebrow">GRAPH AT A GLANCE</span>
          <h2>Connected evidence.</h2>
          <div className="stats-pair">
            <div>
              <strong>{stats?.nodes ?? "—"}</strong>
              <span>nodes</span>
            </div>
            <div>
              <strong>{stats?.edges ?? "—"}</strong>
              <span>edges</span>
            </div>
          </div>
          <div className="query-latency">
            <span>Last query</span>
            <strong>
              {(trace.at(-1)?.ms ?? stats?.last_query_ms)?.toFixed(1) ?? "—"}{" "}
              <small>ms</small>
            </strong>
          </div>
          <p>
            Named Cypher queries. Recorded timings. Every result can be traced
            to the graph.
          </p>
        </section>
      </div>
    </section>
  );
}
