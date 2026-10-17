import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  Inbox,
  LockKeyhole,
  Smartphone,
} from "lucide-react";
import { api, isMock } from "../api";
import type { IngestProgress } from "../api";

export function Onboarding({
  progress,
  onConnected,
}: {
  progress: IngestProgress | null;
  onConnected: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [link, setLink] = useState<{
    telegram_code: string;
    telegram_url: string;
  } | null>(null);
  async function connect(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const value = (name: string) => String(fields.get(name) || "");
    const payload = {
      inboxes: [
        {
          host: value("host"),
          username: value("username"),
          app_password: value("password"),
        },
      ],
      phones: [
        {
          number: value("old_number"),
          carrier: value("old_carrier"),
          status: "retiring" as const,
          drop_at: value("drop_at"),
        },
        {
          number: value("new_number"),
          carrier: value("new_carrier"),
          status: "active" as const,
        },
      ],
    };
    const password = form.elements.namedItem("password");
    if (password instanceof HTMLInputElement) password.value = "";
    setBusy(true);
    setError("");
    try {
      setLink(await api.onboard(payload));
      await api.runIngest();
      onConnected();
    } catch {
      setError(
        "Could not connect. Check the details and try again. Your app password has been cleared.",
      );
    } finally {
      payload.inboxes[0].app_password = "";
      setBusy(false);
    }
  }
  return (
    <section className="page-section onboarding">
      <div className="section-heading">
        <div>
          <span className="eyebrow">START WITH WHAT YOU OWN</span>
          <h1>Make the connections.</h1>
          <p>
            Your inbox holds the clues. Your graph keeps only the evidence it
            needs.
          </p>
        </div>
      </div>
      {isMock && (
        <div className="notice">
          <span className="dot" />
          Demo mode. Use fictional details here. Nothing connects to a real
          inbox.
        </div>
      )}
      <div className="onboarding-grid">
        <form className="connect-form" onSubmit={connect}>
          <div className="form-section">
            <div className="form-heading">
              <Inbox size={20} />
              <h2>Connect an inbox</h2>
            </div>
            <div className="field-grid">
              <label className="wide">
                IMAP server
                <input
                  name="host"
                  required
                  placeholder="imap.gmail.com"
                  autoComplete="off"
                />
              </label>
              <label>
                Email address
                <input
                  name="username"
                  required
                  type="email"
                  placeholder="you@example.com"
                  autoComplete="username"
                />
              </label>
              <label>
                App password
                <input
                  name="password"
                  type="password"
                  required
                  autoComplete="new-password"
                  placeholder="Your inbox app password"
                />
              </label>
            </div>
            <p className="form-help">
              <LockKeyhole size={13} />
              Sent only when you connect. Never returned in a response or saved
              by this browser.
            </p>
          </div>
          <div className="form-section">
            <div className="form-heading">
              <Smartphone size={20} />
              <h2>Declare your numbers</h2>
            </div>
            <div className="field-grid">
              <label>
                Old number
                <input
                  name="old_number"
                  type="tel"
                  required
                  placeholder="+91 … 4321"
                />
              </label>
              <label>
                Old carrier
                <input name="old_carrier" required defaultValue="Vi" />
              </label>
              <label className="wide">
                When will you give it up?
                <input
                  name="drop_at"
                  type="date"
                  required
                  defaultValue="2026-10-31"
                />
              </label>
              <label>
                New number
                <input
                  name="new_number"
                  type="tel"
                  required
                  placeholder="+91 … 7788"
                />
              </label>
              <label>
                New carrier
                <input name="new_carrier" required defaultValue="Jio" />
              </label>
            </div>
          </div>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <button className="primary-button" disabled={busy}>
            {busy ? "Connecting…" : "Connect and discover"}
            <ArrowUpRight size={17} />
          </button>
        </form>
        <div className="onboard-aside">
          <section className="info-card">
            <span className="eyebrow">A SMALLER FOOTPRINT</span>
            <h2>Evidence, not your inbox.</h2>
            <p>
              Lapse keeps message headers and a short snippet to explain each
              connection. Full email bodies, account passwords, and one-time
              codes do not belong in the graph.
            </p>
            <div className="privacy-line">
              <Check size={15} /> Every connection has a source
            </div>
            <div className="privacy-line">
              <Check size={15} /> Every action needs approval
            </div>
          </section>
          <section className="info-card">
            <span className="eyebrow">DISCOVERY</span>
            <h2>
              {progress?.status === "done"
                ? "Your map is ready."
                : progress?.status === "running"
                  ? "Following the clues…"
                  : "Ready when you are."}
            </h2>
            <div className="ingest-stats" aria-live="polite">
              <div>
                <strong>{progress?.emails_scanned ?? 0}</strong>
                <span>emails scanned</span>
              </div>
              <div>
                <strong>{progress?.accounts_found ?? 0}</strong>
                <span>accounts found</span>
              </div>
              <div>
                <strong>{progress?.edges_inferred ?? 0}</strong>
                <span>inferred edges</span>
              </div>
              <div>
                <strong>{progress?.edges_confirmed ?? 0}</strong>
                <span>confirmed edges</span>
              </div>
            </div>
          </section>
          {link && (
            <section className="info-card">
              <span className="eyebrow">TAKE LAPSE WITH YOU</span>
              <h2>Link Telegram</h2>
              <p>Use this code to pair your conversation.</p>
              <code className="link-code">{link.telegram_code}</code>
              <a
                className="text-link"
                href={link.telegram_url}
                target="_blank"
                rel="noreferrer"
              >
                Open Telegram <ArrowUpRight size={15} />
              </a>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
