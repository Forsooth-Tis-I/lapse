import { z } from "zod";
import {
  rootSchema,
  graphDataSchema,
  scenarioResultSchema,
  explanationSchema,
  planSchema,
  changeSchema,
  toolCallRecordSchema,
  agentScreenSchema,
  graphStatsSchema,
  onboardingResultSchema,
  ingestRunSchema,
  graphEventSchema,
  decodeEvent,
  onboardingRequestSchema,
  scenarioRequestSchema,
  planRequestSchema,
  type LapseApi,
} from "./contracts";
import { createMockApi } from "./mock";
export * from "./contracts";

export const isMock = import.meta.env.VITE_USE_MOCK !== "false";
export const baseUrl = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "");
const segment = encodeURIComponent;
export const endpoints = {
  roots: "/api/roots",
  graph: "/api/graph",
  scenarios: "/api/scenarios",
  plans: "/api/plans",
  trace: "/api/trace",
  screen: "/api/agent/screen",
  stats: "/api/stats",
  onboarding: "/api/onboarding",
  ingest: "/api/ingest/run",
  events: "/api/events",
  scenario: (id: string) => `/api/scenarios/${segment(id)}`,
  explain: (id: string, accountId: string) =>
    `/api/scenarios/${segment(id)}/explain/${segment(accountId)}`,
  plan: (id: string) => `/api/plans/${segment(id)}`,
  approve: (id: string) => `/api/changes/${segment(id)}/approve`,
  otp: (id: string) => `/api/changes/${segment(id)}/otp`,
};

export function createRestApi(url = baseUrl): LapseApi {
  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    payload?: unknown,
  ): Promise<T> {
    const response = await fetch(`${url}${path}`, {
      method: payload === undefined ? "GET" : "POST",
      headers:
        payload === undefined
          ? undefined
          : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    if (!response.ok)
      throw new Error(`API request failed (${response.status}). Try again.`);
    return schema.parse(await response.json());
  }
  return {
    getRoots: () => request(endpoints.roots, z.array(rootSchema)),
    getGraph: (scenario) =>
      request(
        `${endpoints.graph}${scenario ? `?scenario=${segment(scenario)}` : ""}`,
        graphDataSchema,
      ),
    createScenario: (input) =>
      request(
        endpoints.scenarios,
        scenarioResultSchema,
        scenarioRequestSchema.parse(input),
      ),
    getScenario: (id) => request(endpoints.scenario(id), scenarioResultSchema),
    explain: (id, accountId) =>
      request(endpoints.explain(id, accountId), explanationSchema),
    createPlan: (input) =>
      request(endpoints.plans, planSchema, planRequestSchema.parse(input)),
    getPlan: (id) => request(endpoints.plan(id), planSchema),
    approveChange: (id) => request(endpoints.approve(id), changeSchema, {}),
    submitOtp: (id, code) => request(endpoints.otp(id), changeSchema, { code }),
    getTrace: (since) =>
      request(
        `${endpoints.trace}${since ? `?since=${segment(since)}` : ""}`,
        z.array(toolCallRecordSchema),
      ),
    getScreen: () => request(endpoints.screen, agentScreenSchema),
    getStats: () => request(endpoints.stats, graphStatsSchema),
    onboard: (input) => {
      const validated = onboardingRequestSchema.safeParse(input);
      if (!validated.success)
        return Promise.reject(new Error("Check the inbox and phone fields."));
      return request(
        endpoints.onboarding,
        onboardingResultSchema,
        validated.data,
      );
    },
    runIngest: () => request(endpoints.ingest, ingestRunSchema, {}),
    subscribe: (onEvent, onError) => {
      const stream = new EventSource(`${url}${endpoints.events}`);
      const receive = (message: MessageEvent<string>) => {
        try {
          onEvent(
            decodeEvent(graphEventSchema.parse(JSON.parse(message.data))),
          );
        } catch {
          onError?.(
            new Error(
              "An event could not be read. Refresh to load the latest state.",
            ),
          );
        }
      };
      stream.onmessage = receive;
      for (const name of [
        "ingest",
        "graph",
        "scenario",
        "plan",
        "exec",
        "signal",
        "trace",
        "chat",
      ])
        stream.addEventListener(name, receive);
      stream.onerror = () =>
        onError?.(new Error("Live connection interrupted. Reconnecting…"));
      return () => stream.close();
    },
  };
}
export const api: LapseApi = isMock ? createMockApi() : createRestApi();
