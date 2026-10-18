import { Camera } from "lucide-react";
import type { AgentScreen, ExecStep } from "../api";

export function AgentPanel({
  screen,
  execution,
}: {
  screen: AgentScreen | null;
  execution: ExecStep | null;
}) {
  return (
    <section className="page-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">AGENT SCREEN</span>
          <h1>What the agent sees.</h1>
          <p>The latest browser view while Lapse carries out an approved change.</p>
        </div>
        <span className="live-label">
          <span className="dot" />
          Live
        </span>
      </div>
      <section className="agent-screen agent-screen-full">
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
            <p>Approve a change in Telegram and the browser view appears here.</p>
          </div>
        )}
        <div className="screen-caption">
          <span className="dot" />
          {execution?.message ||
            screen?.caption ||
            "No actions have been approved."}
        </div>
      </section>
    </section>
  );
}
