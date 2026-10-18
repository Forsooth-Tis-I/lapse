import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Inbox,
  LockKeyhole,
  Smartphone,
} from "lucide-react";
import { api, isMock, onboardingRequestSchema } from "../api";
import type { IngestProgress } from "../api";

export function Onboarding({
  progress,
  onConnected,
}: {
  progress: IngestProgress | null;
  onConnected: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [linking, setLinking] = useState(false);
  const [emailCount, setEmailCount] = useState(1);
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
    const inbox = {
      host: value("host").trim(),
      username: value("username").trim(),
      app_password: value("password"),
    };
    const hasInbox = Object.values(inbox).some(Boolean);
    const payload = {
      display_name: value("display_name").trim() || "Lapse user",
      inboxes: hasInbox ? [inbox] : [],
      phones: [
        {
          number: value("old_number").trim(),
          carrier: value("old_carrier").trim(),
          status: "retiring",
          drop_at: value("drop_at") || undefined,
        },
        {
          number: value("new_number").trim(),
          carrier: value("new_carrier").trim(),
          status: "active",
        },
      ].filter((phone) => phone.number),
      emails: Array.from({ length: emailCount }, (_, index) => {
        const address = value(`email_${index}_address`).trim().toLowerCase();
        return {
          id: value(`email_${index}_id`).trim() || `email:${address}`,
          address,
          kind: value(`email_${index}_kind`),
          hosted_by: value(`email_${index}_hosted_by`).trim() || undefined,
          status: value(`email_${index}_status`),
          closes_at: value(`email_${index}_closes_at`) || undefined,
        };
      }).filter((email) => email.address),
    };
    for (const name of ["host", "username", "password"]) {
      const input = form.elements.namedItem(name);
      if (input instanceof HTMLInputElement) input.value = "";
      fields.delete(name);
    }
    setBusy(true);
    setError("");
    setLink(null);
    let saved = false;
    try {
      const validated = onboardingRequestSchema.parse(payload);
      const emails = validated.emails ?? [];
      const inboxRootIds = validated.inboxes.map((credentials) => {
        const address = credentials.username.trim().toLowerCase();
        const existing = emails.find((email) => email.address.trim().toLowerCase() === address);
        if (existing) return existing.id;
        const root = { id: `email:${address}`, address, kind: "personal", status: "active" } satisfies NonNullable<typeof validated.emails>[number];
        emails.push(root);
        return root.id;
      });
      validated.emails = emails;
      try {
        setLink(await api.onboard(validated));
      } finally {
        for (const credentials of validated.inboxes) {
          credentials.host = "";
          credentials.username = "";
          credentials.app_password = "";
        }
      }
      saved = true;
      onConnected();
      if (inboxRootIds.length) await api.runIngest(inboxRootIds);
    } catch {
      setError(
        saved
          ? "Your details were saved, but discovery could not start."
          : "Could not save. Check your details; an inbox needs its server, email address, and app password. Inbox credentials have been cleared.",
      );
    } finally {
      inbox.host = "";
      inbox.username = "";
      inbox.app_password = "";
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
            <p className="form-help">
              Optional. Leave these fields blank to save only your persona.
            </p>
            <div className="field-grid">
              <label className="wide">
                IMAP server
                <input
                  name="host"
                  placeholder="imap.gmail.com"
                  autoComplete="off"
                />
              </label>
              <label>
                Email address
                <input
                  name="username"
                  type="email"
                  placeholder="you@example.com"
                  autoComplete="off"
                />
              </label>
              <label>
                App password
                <input
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Your inbox app password"
                />
              </label>
            </div>
            <p className="form-help">
              <LockKeyhole size={13} />
              Sent only when you connect. Never returned in a response or stored
              by this app in your browser.
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
                  placeholder="+91 … 4321"
                />
              </label>
              <label>
                Old carrier
                <input name="old_carrier" defaultValue="Vi" />
              </label>
              <label className="wide">
                When will you give it up?
                <input
                  name="drop_at"
                  type="date"
                  defaultValue="2026-10-31"
                />
              </label>
              <label>
                New number
                <input
                  name="new_number"
                  type="tel"
                  placeholder="+91 … 7788"
                />
              </label>
              <label>
                New carrier
                <input name="new_carrier" defaultValue="Jio" />
              </label>
            </div>
          </div>
          <details className="form-section">
            <summary className="form-heading">
              <ChevronDown size={18} /> Persona and email roots
            </summary>
            <div className="field-grid">
              <label className="wide">
                Display name
                <input name="display_name" placeholder="Lapse user" />
              </label>
            </div>
            {Array.from({ length: emailCount }, (_, index) => (
              <div className="form-section" key={index}>
                <h2>Email root {index + 1}</h2>
                <div className="field-grid">
                  <label className="wide">
                    Persona email {index + 1}
                    <input
                      name={`email_${index}_address`}
                      type="email"
                      placeholder="you@college.edu"
                    />
                  </label>
                  <label>
                    Email kind {index + 1}
                    <select
                      name={`email_${index}_kind`}
                      aria-label={`Email kind ${index + 1}`}
                      defaultValue="personal"
                    >
                      <option value="personal">Personal</option>
                      <option value="edu">College</option>
                      <option value="work">Work</option>
                      <option value="custom">Custom domain</option>
                    </select>
                  </label>
                  <label>
                    Email status {index + 1}
                    <select
                      name={`email_${index}_status`}
                      aria-label={`Email status ${index + 1}`}
                      defaultValue="active"
                    >
                      <option value="active">Active</option>
                      <option value="closing">Closing</option>
                      <option value="closed">Closed</option>
                    </select>
                  </label>
                  <label>
                    Hosted by service {index + 1}
                    <input
                      name={`email_${index}_hosted_by`}
                      placeholder="google"
                    />
                  </label>
                  <label>
                    Closure date {index + 1}
                    <input name={`email_${index}_closes_at`} type="date" />
                  </label>
                  <label className="wide">
                    Existing root ID {index + 1}, optional
                    <input
                      name={`email_${index}_id`}
                      placeholder="Leave blank for a new email root"
                    />
                  </label>
                </div>
              </div>
            ))}
            <button
              className="text-link"
              type="button"
              disabled={busy}
              onClick={() => setEmailCount((count) => count + 1)}
            >
              Add another email
            </button>
            <p className="form-help">
              Email kind, hosting service, and closure dates come from you.
              Inbox order does not define them.
            </p>
          </details>
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
          <section className="info-card">
            <span className="eyebrow">TAKE LAPSE WITH YOU</span>
            <h2>Link Telegram</h2>
            {link ? (
              <>
                <p>
                  Send <code>/start {link.telegram_code}</code> to the bot, or
                  open the link. The code works once, for one hour.
                </p>
                <code className="link-code">{link.telegram_code}</code>
                <a
                  className="text-link"
                  href={link.telegram_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open Telegram <ArrowUpRight size={15} />
                </a>
              </>
            ) : (
              <p>Pair the Telegram bot with this account.</p>
            )}
            <button
              type="button"
              className="secondary-button"
              disabled={linking}
              onClick={() => {
                setLinking(true);
                setError("");
                api
                  .linkTelegram()
                  .then(setLink)
                  .catch(() => setError("Could not create a link code. Try again."))
                  .finally(() => setLinking(false));
              }}
            >
              {link ? "New link code" : "Get link code"}
            </button>
          </section>
        </div>
      </div>
    </section>
  );
}
