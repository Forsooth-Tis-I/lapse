import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./components/AccountGraph", () => ({
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
    expect(screen.getByText("5 affected accounts")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Full chain" }));
    expect(screen.getByText("10 affected accounts")).toBeVisible();
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
    expect(screen.getByText("4 affected accounts")).toBeVisible();
    expect(screen.getByText("Not affected in this scenario")).toBeVisible();
    expect(
      screen.queryByText("Email reset AND SMS code"),
    ).not.toBeInTheDocument();
  });
});
