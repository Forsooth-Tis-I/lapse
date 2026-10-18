import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, {currentPlans, reconcileSelection} from "./App";
import { createMockApi } from "./api/mock";
import type { ScenarioResult } from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  const { createMockApi } = await import("./api/mock");
  return { ...actual, api: createMockApi(), isMock: true };
});

vi.mock("./components/AccountGraph", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./components/AccountGraph")>()),
  AccountGraph: ({ results }: { results: ScenarioResult[] }) => (
    <div aria-label="Graph canvas" data-assessed={results.length > 0} data-root={results[0]?.root_ids[0]} />
  ),
}));

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
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

it("opens the scenario a Telegram link points at", async () => {
  const { api } = await import("./api");
  const linked = await api.createScenario({ kind: "lockout", root_ids: ["phone_old"] });
  window.history.pushState({}, "", `/graph?scenario=${linked.id}`);
  await act(async () => {
    render(<App />);
  });
  window.history.pushState({}, "", "/");
  expect(screen.getByRole("combobox", { name: "What if" })).toHaveValue("phone_old");
  expect(screen.getByRole("button", { name: "I lose it" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Full chain" })).toHaveAttribute("aria-pressed", "true");
});

it("runs an initial scenario after onboarding populates an empty graph", async () => {
  const { api } = await import("./api");
  const mock = createMockApi();
  vi.spyOn(api, "getGraph").mockResolvedValueOnce({ nodes: [], edges: [] }).mockImplementation(mock.getGraph);
  vi.spyOn(api, "getRoots").mockResolvedValueOnce([]).mockImplementation(mock.getRoots);
  const create = vi.spyOn(api, "createScenario").mockImplementation(mock.createScenario);
  vi.spyOn(api, "onboard").mockResolvedValue({ telegram_code: "DEMO-123", telegram_url: "https://t.me/" });
  await act(async () => { render(<App />); });
  expect(create).not.toHaveBeenCalled();
  expect(screen.getByText("Choose a number or inbox to assess risk.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Connections" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Connect and discover" }));
  });
  fireEvent.click(screen.getByRole("button", { name: "Account map" }));
  expect(create).toHaveBeenCalledWith({ kind: "takeover", root_ids: ["phone_old"] });
  expect(screen.getByRole("combobox", { name: "What if" })).toHaveValue("phone_old");
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "true");
});

it("keeps an empty graph unassessed", async () => {
  const { api } = await import("./api");
  vi.spyOn(api, "getGraph").mockResolvedValue({ nodes: [], edges: [] });
  vi.spyOn(api, "getRoots").mockResolvedValue([]);
  const create = vi.spyOn(api, "createScenario");
  await act(async () => { render(<App />); });
  expect(create).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("0 direct, 0 full chain")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Plan the fix" })).toBeDisabled();
});

it("does not present pending or failed checks as unaffected and allows retry", async () => {
  const { api } = await import("./api");
  const mock = createMockApi();
  let reject: (reason: Error) => void = () => {};
  const pending = new Promise<ScenarioResult>((_resolve, fail) => { reject = fail; });
  vi.spyOn(api, "createScenario").mockImplementation(mock.createScenario).mockReturnValueOnce(pending);
  await act(async () => { render(<App />); });
  expect(screen.getByText("Checking risk…")).toBeVisible();
  expect(screen.getByRole("button", { name: "Plan the fix" })).toBeDisabled();
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "false");
  await act(async () => {
    fireEvent.change(screen.getByRole("combobox", { name: "Inspect account" }), { target: { value: "dropbox" } });
  });
  expect(screen.getByText("Not assessed yet")).toBeVisible();
  expect(screen.queryByText("Not affected in this scenario")).not.toBeInTheDocument();
  await act(async () => { reject(new Error("unavailable")); });
  expect(screen.getByText("Risk check unavailable")).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("No risk conclusion is available");
  expect(screen.queryByLabelText("0 direct, 0 full chain")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "false");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "true");
});

it("ignores a late scenario response after selecting another root", async () => {
  const { api } = await import("./api");
  const mock = createMockApi();
  const oldResult = await mock.createScenario({ kind: "takeover", root_ids: ["phone_old"] });
  let finish: (result: ScenarioResult) => void = () => {};
  const pending = new Promise<ScenarioResult>((resolve) => { finish = resolve; });
  vi.spyOn(api, "createScenario").mockImplementation(mock.createScenario).mockReturnValueOnce(pending);
  await act(async () => { render(<App />); });
  await act(async () => {
    fireEvent.change(screen.getByRole("combobox", { name: "What if" }), { target: { value: "phone_new" } });
  });
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-root", "phone_new");
  await act(async () => { finish(oldResult); });
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-root", "phone_new");
});

it("preserves a valid selection on refresh and replaces a removed root", async () => {
  const { api } = await import("./api");
  const mock = createMockApi();
  let onEvent: Parameters<typeof api.subscribe>[0] = () => {};
  vi.spyOn(api, "subscribe").mockImplementation((listener) => { onEvent = listener; return () => {}; });
  const roots = await mock.getRoots();
  const getRoots = vi.spyOn(api, "getRoots").mockImplementation(mock.getRoots);
  await act(async () => { render(<App />); });
  await act(async () => {
    fireEvent.change(screen.getByRole("combobox", { name: "What if" }), { target: { value: "phone_new" } });
    fireEvent.click(screen.getByRole("button", { name: "I lose it" }));
  });
  const refresh = () => onEvent({ kind: "ingest", data: {
    status: "done", emails_scanned: 0, accounts_found: 0, edges_confirmed: 0, edges_inferred: 0,
  } });
  let finish: (value: ScenarioResult) => void = () => {};
  const pending = new Promise<ScenarioResult>((resolve) => { finish = resolve; });
  vi.spyOn(api, "createScenario").mockReturnValueOnce(pending);
  await act(async () => { refresh(); });
  expect(screen.getByRole("combobox", { name: "What if" })).toHaveValue("phone_new");
  expect(screen.getByRole("button", { name: "I lose it" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Checking risk…")).toBeVisible();
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "false");
  await act(async () => {
    finish(await mock.createScenario({ kind: "lockout", root_ids: ["phone_new"] }));
  });
  expect(screen.getByLabelText("Graph canvas")).toHaveAttribute("data-assessed", "true");
  getRoots.mockResolvedValue(roots.filter((root) => root.id !== "phone_new"));
  await act(async () => { refresh(); });
  expect(screen.getByRole("combobox", { name: "What if" })).toHaveValue("phone_old");
  expect(screen.getByRole("button", { name: "Someone else gets it" })).toHaveAttribute("aria-pressed", "true");
});

it("defaults to lockout when the only available root is an active email", async () => {
  const roots = await createMockApi().getRoots();
  const email = roots.find((root) => root.kind === "email");
  if (!email) throw new Error("Missing fixture email");
  expect(reconcileSelection([{ ...email, status: "active" }], { target: null, mode: "takeover" }))
    .toEqual({ target: email.id, mode: "lockout" });
});
