import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ChatReply } from "../api";
import { ChatPanel } from "./ChatPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup() {
  const handlers = {
    onPlanRoot: vi.fn(),
    onOpenWeb: vi.fn(),
    onShowTrace: vi.fn(),
    onReply: vi.fn(),
    onApproveChanges: vi.fn<(ids: string[]) => Promise<void>>().mockResolvedValue(undefined),
  };
  render(<ChatPanel {...handlers} />);
  return handlers;
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message Lapse"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
}

describe("chat with the graph agent", () => {
  it("shows Working while a reply is pending, then renders its text and trace links", async () => {
    let finish: (reply: ChatReply) => void = () => {};
    const chat = vi.spyOn(api, "chat").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const handlers = setup();
    send("Why is Gmail exposed?");
    expect(screen.getByRole("status")).toHaveTextContent("Working…");
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    expect(chat).toHaveBeenCalledExactlyOnceWith("Why is Gmail exposed?");
    const reply: ChatReply = {
      text: "Gmail uses your old recovery phone under the methods we model.",
      buttons: [],
      tool_calls: ["takeover_if_reassigned", "explain"],
    };
    await act(async () => finish(reply));
    expect(screen.getByText(reply.text)).toBeVisible();
    expect(handlers.onReply).toHaveBeenCalledWith(reply);
    fireEvent.click(screen.getByRole("button", { name: "View trace for explain" }));
    expect(handlers.onShowTrace).toHaveBeenCalledWith("explain", undefined);
    expect(screen.getByLabelText("Message Lapse")).toHaveValue("");
    expect(screen.queryByText("Working…")).not.toBeInTheDocument();
  });

  it("uses the backend button payloads for navigation, planning, and explicit approval", async () => {
    vi.spyOn(api, "chat").mockResolvedValue({
      text: "Review these changes.",
      tool_calls: ["plan_retirement"],
      buttons: [
        { label: "Review in web", action: "open_web", payload: { path: "/plans/plan-old" } },
        { label: "Plan the fix", action: "plan_root", payload: { root_id: "phone_old" } },
        { label: "Approve all T1–T3", action: "approve_changes", payload: { change_ids: ["change-1", "change-2"], approval_token: "private-human-token" } },
      ],
    });
    const handlers = setup();
    send("Plan the fix");
    await screen.findByText("Review these changes.");
    expect(handlers.onApproveChanges).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Review in web" }));
    expect(handlers.onOpenWeb).toHaveBeenCalledWith("/plans/plan-old");
    fireEvent.click(screen.getByRole("button", { name: "Plan the fix" }));
    expect(handlers.onPlanRoot).toHaveBeenCalledWith("phone_old");
    fireEvent.click(screen.getByRole("button", { name: "Approve all T1–T3" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Approved" })).toBeDisabled());
    expect(handlers.onApproveChanges).toHaveBeenCalledExactlyOnceWith(["change-1", "change-2"]);
    expect(document.body.innerHTML).not.toContain("private-human-token");
  });

  it("keeps failed approvals retryable and reports the error without exposing tokens", async () => {
    vi.spyOn(api, "chat").mockResolvedValue({
      text: "Ready for approval.",
      tool_calls: [],
      buttons: [{ label: "Approve", action: "approve_changes", payload: { change_ids: ["change-1"], approval_token: "private-token" } }],
    });
    const handlers = setup();
    handlers.onApproveChanges.mockRejectedValueOnce(new Error("private-token"));
    send("Plan my changes");
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Approval could not be completed");
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(document.body.textContent).not.toContain("private-token");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Approved" })).toBeDisabled());
  });

  it("restores the draft after a failed chat request", async () => {
    vi.spyOn(api, "chat").mockRejectedValue(new Error("untrusted response body"));
    setup();
    send("What happens to my college email?");
    expect(await screen.findByRole("alert")).toHaveTextContent("The message could not be sent");
    expect(screen.getByLabelText("Message Lapse")).toHaveValue("What happens to my college email?");
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
    expect(document.body.textContent).not.toContain("untrusted response body");
  });
});

it("keeps a reply linked to its captured invocation after another reply uses the same tool", async () => {
  vi.spyOn(api, "chat").mockResolvedValue({text: "A result", buttons: [], tool_calls: ["resolve"]});
  const handlers = setup();
  const row = {id: "first:0", tool: "resolve", at: "2026-10-17T10:00:00Z", args: {}, query_name: "resolve", rows: 1, ms: 2, outcome: "ok"};
  handlers.onReply.mockResolvedValueOnce([row]).mockResolvedValueOnce([row, {...row, id: "second:0"}]);
  send("first question");
  await screen.findByText("A result");
  send("second question");
  await waitFor(() => expect(screen.getAllByText("A result")).toHaveLength(2));
  fireEvent.click(screen.getAllByRole("button", {name: "View trace for resolve"})[0]);
  expect(handlers.onShowTrace).toHaveBeenLastCalledWith("resolve", row);
});
