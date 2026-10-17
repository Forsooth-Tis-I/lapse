import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { createMockApi } from "../api/mock";
import { PlanBoard } from "./PlanBoard";
import { Onboarding } from "./Onboarding";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("approval and connection controls", () => {
  it("bulk approval excludes in-person steps", async () => {
    const mock = createMockApi();
    const plan = await mock.createPlan({
      old_root: "phone_old",
      new_root: "phone_new",
    });
    const approve = vi
      .spyOn(api, "approveChange")
      .mockImplementation(async (id) => {
        const step = plan.steps.find((item) => item.id === id);
        if (!step) throw new Error("Missing step");
        return { ...step, status: "approved" };
      });
    render(
      <PlanBoard
        plans={[plan]}
        creating={false}
        onCreate={() => {}}
        onChange={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve all T1–T3" }));
    await waitFor(() => expect(approve).toHaveBeenCalledTimes(4));
    expect(approve).not.toHaveBeenCalledWith(
      plan.steps.find((step) => step.tier === 4)?.id,
    );
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeVisible();
  });

  it("clears an inbox secret before the request resolves and displays only the link code", async () => {
    let finish: (value: {
      telegram_code: string;
      telegram_url: string;
    }) => void = () => {};
    const posted: string[] = [];
    vi.spyOn(api, "onboard").mockImplementation((input) => {
      posted.push(input.inboxes[0].app_password);
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    vi.spyOn(api, "runIngest").mockResolvedValue({ started: true });
    render(<Onboarding progress={null} onConnected={() => {}} />);
    fireEvent.change(screen.getByLabelText("IMAP server"), {
      target: { value: "imap.example.test" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "demo@example.test" },
    });
    fireEvent.change(screen.getByLabelText("App password"), {
      target: { value: "fictional-app-secret" },
    });
    fireEvent.change(screen.getByLabelText("Old number"), {
      target: { value: "+910000004321" },
    });
    fireEvent.change(screen.getByLabelText("New number"), {
      target: { value: "+910000007788" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Connect and discover" }),
    );
    expect(screen.getByLabelText("App password")).toHaveValue("");
    expect(posted).toEqual(["fictional-app-secret"]);
    finish({ telegram_code: "DEMO-123", telegram_url: "https://t.me/" });
    await screen.findByText("DEMO-123");
    expect(document.body.textContent).not.toContain("fictional-app-secret");
  });
});
