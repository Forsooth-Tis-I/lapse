import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { Onboarding } from "./Onboarding";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Connect and discover" }));
}

const link = { telegram_code: "PAIR-123", telegram_url: "https://t.me/LapseAlfredBot?start=PAIR-123" };

describe("onboarding persona and write-only inbox credentials", () => {
  it("saves explicit email metadata and optional phones without an inbox or ingestion", async () => {
    const onboard = vi.spyOn(api, "onboard").mockResolvedValue(link);
    const ingest = vi.spyOn(api, "runIngest");
    const connected = vi.fn();
    render(<Onboarding progress={null} onConnected={connected} />);
    fireEvent.click(screen.getByText("Persona and email roots"));
    fill("Display name", "Demo persona");
    fill("Persona email 1", "STUDENT@college.test");
    fill("Email kind 1", "edu");
    fill("Email status 1", "closing");
    fill("Hosted by service 1", "gmail");
    fill("Closure date 1", "2026-12-31");
    fill("Existing root ID 1, optional", "email_college");
    fireEvent.click(screen.getByRole("button", { name: "Add another email" }));
    fill("Persona email 2", "person@example.test");
    fill("Old number", "+910000004321");
    fill("When will you give it up?", "");
    submit();
    await screen.findByText("PAIR-123");
    expect(onboard).toHaveBeenCalledWith(expect.objectContaining({
      display_name: "Demo persona",
      inboxes: [],
      phones: [{ number: "+910000004321", carrier: "Vi", status: "retiring", drop_at: undefined }],
      emails: [
        { id: "email_college", address: "student@college.test", kind: "edu", status: "closing", hosted_by: "gmail", closes_at: "2026-12-31" },
        { id: "email:person@example.test", address: "person@example.test", kind: "personal", status: "active", hosted_by: undefined, closes_at: undefined },
      ],
    }));
    expect(connected).toHaveBeenCalledOnce();
    expect(ingest).not.toHaveBeenCalled();
  });

  it("rejects an incomplete inbox and clears all supplied credentials", async () => {
    const onboard = vi.spyOn(api, "onboard");
    render(<Onboarding progress={null} onConnected={() => {}} />);
    fill("Email address", "reader@example.test");
    fill("App password", "never-retain-this-secret");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("an inbox needs its server");
    expect(onboard).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email address")).toHaveValue("");
    expect(screen.getByLabelText("App password")).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("never-retain-this-secret");
  });

  it("clears credentials after failure without displaying backend secret-bearing errors", async () => {
    vi.spyOn(api, "onboard").mockRejectedValue(new Error("failed with never-retain-this-secret"));
    const ingest = vi.spyOn(api, "runIngest");
    const connected = vi.fn();
    render(<Onboarding progress={null} onConnected={connected} />);
    fill("IMAP server", "imap.example.test");
    fill("Email address", "reader@example.test");
    fill("App password", "never-retain-this-secret");
    submit();
    await screen.findByRole("alert");
    expect(screen.getByLabelText("IMAP server")).toHaveValue("");
    expect(screen.getByLabelText("Email address")).toHaveValue("");
    expect(screen.getByLabelText("App password")).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("never-retain-this-secret");
    expect(connected).not.toHaveBeenCalled();
    expect(ingest).not.toHaveBeenCalled();
  });

  it("retains the saved Telegram link when inbox discovery cannot be queued", async () => {
    vi.spyOn(api, "onboard").mockResolvedValue(link);
    vi.spyOn(api, "runIngest").mockRejectedValue(new Error("queue unavailable"));
    const connected = vi.fn();
    render(<Onboarding progress={null} onConnected={connected} />);
    fill("IMAP server", "imap.example.test");
    fill("Email address", "reader@example.test");
    fill("App password", "fictional-secret");
    submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Your details were saved"));
    expect(screen.getByText("PAIR-123")).toBeVisible();
    expect(connected).toHaveBeenCalledOnce();
  });
});
