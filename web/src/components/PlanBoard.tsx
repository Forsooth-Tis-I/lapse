import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  Clock3,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import { api, changeSchema, planSchema } from "../api";
import type { Change, Plan, Root } from "../api";

const tiers = {
  1: "Automatic",
  2: "Browser + your code",
  3: "You do it",
  4: "Manual",
};
const statusLabel = {
  proposed: "Needs approval",
  approved: "Approved",
  running: "In progress",
  awaiting_otp: "Waiting for your code",
  awaiting_user: "Your turn",
  done: "Verified",
  failed: "Failed",
  skipped: "Skipped",
};

function AdditionalDetails({value, known}: {value: Record<string, unknown>; known: object}) {
  const fields = Object.entries(value).filter(([key, item]) => !(key in known) && item != null);
  if (!fields.length) return null;
  return <details className="additional-details"><summary>Additional planner details</summary>
    <dl>{fields.map(([key, item]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof item === "object" ? JSON.stringify(item) : String(item)}</dd></div>)}</dl>
  </details>;
}

function ChangeCard({
  step,
  exposure,
  onChange,
  approvingAll,
}: {
  approvingAll: boolean;
  step: Change;
  exposure: number;
  onChange: (step: Change) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [code, setCode] = useState("");
  async function approve() {
    setBusy(true);
    setError("");
    try {
      onChange(await api.approveChange(step.id));
    } catch {
      setError("Approval failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  async function submitCode(event: React.FormEvent) {
    event.preventDefault();
    const submitted = code;
    setCode("");
    setBusy(true);
    setError("");
    try {
      onChange(await api.submitOtp(step.id, submitted));
      setSubmitted(true);
    } catch {
      setError("The code could not be submitted. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className={`change-card status-${step.status}`}>
      <div className="step-number">
        {step.status === "done" ? (
          <Check size={22} />
        ) : (
          String(step.order).padStart(2, "0")
        )}
      </div>
      <div className="change-body">
        <div className="flex items-center gap-3 flex-wrap">
          <h3>{step.account_label}</h3>
          <span className={`tier tier-${step.tier}`}>
            T{step.tier} · {tiers[step.tier]}
          </span>
        </div>
        <p>
          {step.note ||
            `Move ${step.role.replaceAll("_", " ")} to your new contact.`}
        </p>
        <div className="exposure-line">
          <span>
            {step.exposure_removed} account
            {step.exposure_removed !== 1 ? "s" : ""} of exposure removed
          </span>
          <div className="exposure-track">
            <span
              style={{
                width: `${Math.min(100, (step.exposure_removed / Math.max(exposure, 1)) * 100)}%`,
              }}
            />
          </div>
        </div>
        {step.requires_old_root && (
          <div className="due">
            <Clock3 size={13} /> Old contact needed
            {step.due ? ` · Finish by ${step.due}` : ""}
          </div>
        )}
        {step.status === "awaiting_otp" && (
          <form className="otp-form" onSubmit={submitCode}>
            <label htmlFor={`otp-${step.id}`}>
              <KeyRound size={14} /> Enter the verification code requested by the executor
            </label>
            <div className="flex gap-2">
              <input
                id={`otp-${step.id}`}
                aria-label={`Code for ${step.account_label}`}
                type="password"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                minLength={1}
                maxLength={128}
              />
              <button
                className="primary-button"
                disabled={busy || code.length === 0}
              >
                Submit code
              </button>
            </div>
            {submitted && <p role="status">Code submitted. Waiting for the executor to verify it.</p>}
            <small>Used once. Never saved or shown in the trace.</small>
          </form>
        )}
        {step.status === "awaiting_user" && step.settings_url && (
          <a
            className="text-link"
            href={step.settings_url}
            target="_blank"
            rel="noreferrer"
          >
            Open account settings <ArrowUpRight size={15} />
          </a>
        )}
        <AdditionalDetails value={step} known={changeSchema.shape} />
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
      </div>
      <div className="step-action">
        <span className={`status-pill ${step.status}`}>
          {statusLabel[step.status]}
        </span>
        {(step.status === "proposed" || step.status === "failed") && (
          <button
            className="secondary-button"
            disabled={busy || approvingAll}
            onClick={approve}
          >
            {busy
              ? "Approving…"
              : step.tier === 4
                ? "Acknowledge"
                : "Approve step"}
          </button>
        )}
      </div>
    </article>
  );
}

export function PlanBoard({
  plans,
  onChange,
  onCreate,
  creating,
  roots = [],
  onCreateRoot,
}: {
  plans: Plan[];
  roots?: Root[];
  onCreateRoot?: (rootId: string) => void;
  onChange: (step: Change) => void;
  onCreate: () => void;
  creating: boolean;
}) {
  const [rootId, setRootId] = useState("");
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const steps = plans.flatMap((plan) => plan.steps);
  const pending = steps.filter(
    (step) => step.status === "proposed" && step.tier <= 3,
  );
  async function approveAll() {
    setApproving(true);
    setError("");
    try {
      for (const step of pending) onChange(await api.approveChange(step.id));
    } catch {
      setError(
        "Some steps could not be approved. The remaining steps are still waiting for approval.",
      );
    } finally {
      setApproving(false);
    }
  }
  return (
    <section className="page-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">YOUR NEXT MOVES</span>
          <h1>Close the loose ends.</h1>
          <p>
            The graph puts the highest-impact fix first. You stay in control.
          </p>
        </div>
        {steps.length > 0 && (
          <button
            className="primary-button"
            disabled={approving || pending.length === 0}
            onClick={approveAll}
          >
            <ShieldCheck size={17} />
            {approving ? "Approving…" : "Approve all T1–T3"}
          </button>
        )}
      </div>
      {onCreateRoot && <form className="root-plan-form" onSubmit={(event) => { event.preventDefault(); if (rootId) onCreateRoot(rootId); }}>
        <label>Plan from a root<select aria-label="Root to retire" required value={rootId} onChange={(event) => setRootId(event.target.value)}>
          <option value="">Choose a phone, email, or device</option>
          {roots.map((root) => <option key={root.id} value={root.id}>{root.label} · {root.status}</option>)}
        </select></label>
        <button className="secondary-button" disabled={creating || !rootId}>{creating ? "Building plan…" : "Plan this root"}</button>
      </form>}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {plans.length === 0 ? (
        <div className="empty-panel">
          <ShieldCheck size={34} />
          <h2>A smaller risk, one change at a time.</h2>
          <p>Build an ordered plan for the selected scenario, or choose a root above.</p>
          <button
            className="primary-button"
            disabled={creating}
            onClick={onCreate}
          >
            {creating ? "Building plan…" : "Build my fix plan"}
          </button>
        </div>
      ) : (
        plans.map((plan) => (
          <section className="plan-group" key={plan.id}>
            <div className="plan-heading">
              <h2>
                {roots.find((root) => root.id === plan.old_root)?.label ?? plan.old_root}
              </h2>
              <span>
                {plan.steps.filter((s) => s.status === "done").length}/
                {plan.steps.length} verified · {plan.exposure_before} →{" "}
                {plan.exposure_after} affected
              </span>
            </div>
            <AdditionalDetails value={plan} known={planSchema.shape} />
            {!plan.feasible && (
              <p className="warning-note">
                This plan needs your attention. Some changes may no longer be
                possible before the deadline.
              </p>
            )}
            {[...plan.steps]
              .sort((a, b) => a.order - b.order)
              .map((step) => (
                <ChangeCard
                  key={step.id}
                  step={step}
                  approvingAll={approving}
                  exposure={plan.exposure_before}
                  onChange={onChange}
                />
              ))}
          </section>
        ))
      )}
      <p className="footnote">
        Approval permits the listed action. A change is complete only after
        verification. Manual T4 steps are always separate.
      </p>
    </section>
  );
}
