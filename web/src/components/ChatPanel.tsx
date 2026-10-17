import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, MessageCircle, Send, Terminal } from "lucide-react";
import { api, type ToolCallRecord, type ChatReply } from "../api";
import "./chat.css";

type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; reply: ChatReply; traceRecords: (ToolCallRecord | undefined)[] };

type RequestState = "idle" | "sending" | "approving";

export function ChatPanel({
  onPlanRoot,
  onOpenWeb,
  onShowTrace,
  onReply,
  onApproveChanges,
}: {
  onPlanRoot: (rootId: string) => void;
  onOpenWeb: (path: string) => void;
  onShowTrace: (toolName: string, record?: ToolCallRecord) => void;
  onReply: (reply: ChatReply) => Promise<ToolCallRecord[]> | void;
  onApproveChanges: (changeIds: string[]) => Promise<void>;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [request, setRequest] = useState<RequestState>("idle");
  const [error, setError] = useState("");
  const [approved, setApproved] = useState<Set<string>>(() => new Set());
  const history = useRef<HTMLDivElement>(null);
  const busy = request !== "idle";

  useEffect(() => {
    if (history.current)
      history.current.scrollTop = history.current.scrollHeight;
  }, [messages, request]);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setDraft("");
    setError("");
    setRequest("sending");
    setMessages((current) => [...current, { role: "user", text: text.trim() }]);
    try {
      const reply = await api.chat(text.trim());
      const records = await onReply(reply) ?? [];
      const used = new Set<string>();
      const traceRecords = [...reply.tool_calls].reverse().map((tool) => {
        const record = [...records].reverse().find((row) => row.tool === tool && !used.has(row.id.split(":")[0]));
        if (record) used.add(record.id.split(":")[0]);
        return record;
      }).reverse();
      setMessages((current) => [...current, { role: "assistant", reply, traceRecords }]);
    } catch {
      setError("The message could not be sent. Please try again.");
      setDraft(text);
    } finally {
      setRequest("idle");
    }
  }

  async function approve(key: string, changeIds: string[]) {
    if (busy || approved.has(key)) return;
    setError("");
    setRequest("approving");
    try {
      await onApproveChanges(changeIds);
      setApproved((current) => new Set([...current, key]));
    } catch {
      setError("Approval could not be completed. Review the plan and try again.");
    } finally {
      setRequest("idle");
    }
  }

  return (
    <section className="chat-panel" aria-label="Chat with Lapse">
      <div className="panel-title">
        <span><MessageCircle size={16} /> Ask Lapse</span>
        <span className="mono">GRAPH-GROUNDED</span>
      </div>
      <div className="chat-history" ref={history} role="log" aria-label="Conversation" aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-intro">
            <h2>Start with a question.</h2>
            <p>The same agent as Telegram, with every tool call linked to its trace.</p>
            <button className="chat-suggestion" onClick={() => void send("Show risk for 4321")}>
              What if a stranger gets ••4321? <ArrowUpRight size={15} />
            </button>
          </div>
        )}
        {messages.map((message, messageIndex) => (
          <article className={`chat-message ${message.role}`} key={messageIndex}>
            <span className="chat-speaker">{message.role === "user" ? "You" : "Lapse"}</span>
            <p>{message.role === "user" ? message.text : message.reply.text}</p>
            {message.role === "assistant" && (
              <>
                <div className="chat-actions">
                  {message.reply.buttons.map((button, buttonIndex) => {
                    const key = `${messageIndex}-${buttonIndex}`;
                    return (
                      <button
                        key={key}
                        disabled={busy || approved.has(key)}
                        onClick={() => {
                          switch (button.action) {
                            case "open_web":
                              onOpenWeb(button.payload.path);
                              break;
                            case "plan_root":
                              onPlanRoot(button.payload.root_id);
                              break;
                            case "approve_changes":
                              void approve(key, button.payload.change_ids);
                              break;
                          }
                        }}
                      >
                        {approved.has(key) ? "Approved" : button.label}
                        <ArrowUpRight size={14} />
                      </button>
                    );
                  })}
                </div>
                {message.reply.tool_calls.length > 0 && (
                  <div className="chat-tools" aria-label="Tools used for this reply">
                    {message.reply.tool_calls.map((tool, index) => (
                      <button key={`${tool}-${index}`} onClick={() => onShowTrace(tool, message.traceRecords[index])} aria-label={`View trace for ${tool}`}>
                        <Terminal size={13} /> {tool}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </article>
        ))}
      </div>
      <div className="chat-status" role="status">
        {request === "sending" ? "Working…" : request === "approving" ? "Approving changes…" : "Answers use the methods we model."}
      </div>
      {error && <p className="chat-error" role="alert">{error}</p>}
      <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send(draft); }}>
        <label className="sr-only" htmlFor="chat-message">Message Lapse</label>
        <input id="chat-message" autoComplete="off" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Ask about a number, email, or account…" disabled={busy} />
        <button type="submit" aria-label="Send message" disabled={busy || !draft.trim()}><Send size={17} /></button>
      </form>
      <p className="chat-privacy">Use the dedicated forms for passwords and OTPs.</p>
    </section>
  );
}
