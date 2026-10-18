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
    expect(screen.getByLabelText("5 direct, 10 full chain")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Full chain" }));
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
    expect(screen.getByLabelText(/, 4 full chain$/)).toBeVisible();
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

it("runs a scenario for whichever number or inbox is picked", async () => {
  await act(async () => {
    render(<App />);
  });
  await act(async () => {
    fireEvent.change(screen.getByRole("combobox", { name: "What if" }), {
      target: { value: "phone_new" },
    });
  });
  fireEvent.click(screen.getByRole("button", { name: "I lose it" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^If you lose your number/);
  expect(screen.getByRole("button", { name: "I lose it" })).toHaveAttribute("aria-pressed", "true");
});
