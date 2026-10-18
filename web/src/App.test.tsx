import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, {currentPlans} from "./App";
import { createMockApi } from "./api/mock";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  const { createMockApi } = await import("./api/mock");
  return { ...actual, api: createMockApi(), isMock: true };
});

vi.mock("./components/AccountGraph", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./components/AccountGraph")>()),
  AccountGraph: () => <div aria-label="Graph canvas" />,
}));

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("scenario and execution integration", () => {
  it("refreshes an open derivation when the approved Gmail fix removes the path", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByLabelText("5 at 1 hop, 10 at 3 hops")).toBeVisible();
    const slider = screen.getByRole("slider", { name: "Hops" });
    expect(slider).toHaveAttribute("aria-valuetext", "1 of 3, 5 accounts");
    fireEvent.change(slider, { target: { value: "3" } });
    expect(slider).toHaveAttribute("aria-valuetext", "3 of 3, 10 accounts");
    await act(async () => {
      fireEvent.change(
        screen.getByRole("combobox", { name: "Inspect account" }),
        { target: { value: "dropbox" } },
      );
    });
    expect(screen.getByText("Email reset AND SMS code")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Fix plan" }));
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Build my fix plan" }),
      );
    });
    const googleCard = screen
      .getByRole("heading", { name: "Google" })
      .closest("article");
    if (!googleCard) throw new Error("Google change missing");
    await act(async () => {
      fireEvent.click(
        within(googleCard).getByRole("button", { name: "Approve step" }),
      );
      await vi.advanceTimersByTimeAsync(950);
    });
    fireEvent.change(screen.getByLabelText("Code for Google"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
      await vi.advanceTimersByTimeAsync(700);
    });
    fireEvent.click(screen.getByRole("button", { name: "Account map" }));
    expect(screen.getByLabelText(/, 4 at \d hops?$/)).toBeVisible();
    expect(screen.getByText("Not affected in this scenario")).toBeVisible();
    expect(
      screen.queryByText("Email reset AND SMS code"),
    ).not.toBeInTheDocument();
  });
});


it("offers only the latest plan for each root, avoiding duplicate bulk approvals", async () => {
  const plan = await createMockApi().createPlan({old_root:"phone_old", new_root:"phone_new"});
  const latest = {...plan, id: "latest", created_at: "2026-10-18T10:00:00Z"};
  const older = {...plan, created_at: "2026-10-17T10:00:00Z"};
  expect(currentPlans([latest, older])).toEqual([latest]);
});
