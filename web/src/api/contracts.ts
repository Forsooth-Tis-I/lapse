import { z } from "zod";

const date = z.iso.date();
const datetime = z.string().datetime({ offset: true });
const optionalText = z.string().nullable().default(null);
const optionalDate = date.nullable().default(null);
const optionalDatetime = datetime.nullable().default(null);
export const scenarioKindSchema = z.enum(["takeover", "lockout"]);
export const rootSchema = z.object({
  id: z.string(),
  kind: z.enum(["phone", "email", "domain", "device"]),
  label: z.string(),
  status: z
    .enum([
      "active",
      "retiring",
      "inactive",
      "closing",
      "closed",
      "expired",
      "sold",
      "lost",
      "unknown",
    ])
    .default("active"),
  confirmed: z.boolean().default(true),
  last4: optionalText,
  e164: optionalText,
  country: optionalText,
  carrier: optionalText,
  drop_at: optionalDate,
  inactive_since: optionalDate,
  reissue_after: optionalDate,
  address: optionalText,
  email_kind: z
    .enum(["personal", "edu", "work", "custom"])
    .nullable()
    .default(null),
  hosted_by_service: optionalText,
  closes_at: optionalDate,
  name: optionalText,
  registrar: optionalText,
  expires_at: optionalDate,
  device_kind: z.enum(["phone", "laptop", "key"]).nullable().default(null),
});
export const accountSchema = z.object({
  id: z.string(),
  service_id: z.string(),
  display: z.string(),
  identifier: optionalText,
  status: z.enum(["active", "closed"]).default("active"),
  modelled: z.boolean().default(true),
  first_seen: optionalDatetime,
  last_seen: optionalDatetime,
});
export const evidenceSchema = z.object({
  id: z.string(),
  msg_id: z.string(),
  inbox: z.string(),
  date: datetime,
  sender: z.string(),
  subject: z.string(),
  snippet: z.string(),
  event: z.enum([
    "signup",
    "verify_email",
    "otp_sms_notice",
    "otp_email",
    "login_alert",
    "new_device",
    "twofa_enabled",
    "twofa_disabled",
    "contact_changed",
    "password_reset",
    "deactivation_notice",
    "domain_expiry",
    "other",
  ]),
});
export const reachedSchema = z.object({
  node_id: z.string(),
  label: z.string(),
  node_type: z.enum(["Account", "Root"]),
  round: z.number().int(),
  via_method: optionalText,
});
export const scenarioRequestSchema = z.object({
  kind: scenarioKindSchema,
  root_ids: z.array(z.string()).min(1),
});
export const scenarioResultSchema = z.object({
  id: z.string(),
  kind: scenarioKindSchema,
  root_ids: z.array(z.string()),
  actor: z.enum(["stranger", "user"]),
  rounds: z.number().int(),
  affected_accounts: z.array(reachedSchema),
  recovery_lost_accounts: z.array(reachedSchema).optional(),
  lost_now_accounts: z.array(reachedSchema).optional(),
  direct_accounts: z.array(z.string()),
  unknown_accounts: z.array(z.string()),
  total_accounts: z.number().int(),
  ms: z.number(),
});
export const pathStepSchema = z.object({
  from_id: z.string(),
  from_label: z.string(),
  to_id: z.string(),
  to_label: z.string(),
  method_id: z.string(),
  method_label: z.string(),
  round: z.number().int(),
  evidence: z.array(evidenceSchema).default([]),
});
export const explanationSchema = z.object({
  scenario_id: z.string(),
  account_id: z.string(),
  outcome: z.enum(["path", "not_affected", "not_in_graph"]),
  steps: z.array(pathStepSchema).default([]),
});
const useRoleSchema = z.enum([
  "login_email",
  "recovery_email",
  "login_phone",
  "recovery_phone",
  "sms_2fa",
  "totp_device",
]);
export const changeSchema = z.looseObject({
  id: z.string(),
  plan_id: z.string(),
  order: z.number().int(),
  account_id: z.string(),
  account_label: z.string(),
  role: useRoleSchema,
  roles: z.array(useRoleSchema).optional(),
  title: z.string().nullable().optional(),
  from_root: z.string(),
  to_root: z.string().nullable(),
  tier: z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4)]),
  requires_old_root: z.boolean(),
  due: optionalDate,
  exposure_removed: z.number().int().default(0),
  status: z
    .enum([
      "proposed",
      "approved",
      "running",
      "awaiting_otp",
      "awaiting_user",
      "done",
      "failed",
      "skipped",
    ])
    .default("proposed"),
  settings_url: optionalText,
  note: optionalText,
});
export const planSchema = z.looseObject({
  id: z.string(),
  kind: scenarioKindSchema,
  old_root: z.string(),
  new_root: z.string().nullable(),
  deadline: date.nullable(),
  feasible: z.boolean(),
  exposure_before: z.number().int(),
  exposure_after: z.number().int(),
  takeover_before: z.number().int().optional(),
  takeover_after: z.number().int().optional(),
  lockout_before: z.number().int().optional(),
  lockout_after: z.number().int().optional(),
  remaining_accounts: z.array(z.string()).optional(),
  unknown_accounts: z.array(z.string()).optional(),
  note: z.string().nullable().optional(),
  steps: z.array(changeSchema),
  created_at: datetime,
});
export const planRequestSchema = z.object({
  old_root: z.string(),
  new_root: z.string().optional(),
  deadline: date.optional(),
});
export const execStepSchema = z.object({
  change_id: z.string(),
  kind: z.enum([
    "progress",
    "screenshot",
    "need_otp",
    "need_user",
    "done",
    "failed",
  ]),
  message: z.string(),
  channel: optionalText,
  url: optionalText,
  at: datetime,
});
export const signalSchema = z.object({
  id: z.string(),
  kind: z.enum([
    "reissue_countdown",
    "closing_email",
    "domain_expiry",
    "stale_root",
    "new_device",
    "missed_account",
    "policy_event",
  ]),
  root_id: z.string().nullable(),
  at: datetime,
  title: z.string(),
  detail: z.string(),
  deadline: optionalDate,
  status: z.enum(["open", "acted", "dismissed"]).default("open"),
});
export const toolCallRecordSchema = z.object({
  id: z.string(),
  at: datetime,
  tool: z.string(),
  args: z.record(z.string(), z.unknown()),
  query_name: z.string().nullable(),
  ms: z.number(),
  rows: z.number().int(),
  outcome: z.enum([
    "path",
    "memory",
    "not_in_graph",
    "unknown_root",
    "ok",
    "error",
  ]),
});
export const graphEventSchema = z.object({
  type: z.enum([
    "ingest",
    "graph",
    "scenario",
    "plan",
    "exec",
    "signal",
    "trace",
    "chat",
  ]),
  uid: z.string(),
  at: datetime,
  data: z.record(z.string(), z.unknown()),
});
export const graphNodeSchema = z.object({
  id: z.string(),
  label: z.string(),
  node_type: z.enum(["Root", "Account"]),
  root: rootSchema.optional(),
  account: accountSchema.optional(),
});
export const graphEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  label: z.string(),
  confirmed: z.boolean(),
  method_id: z.string().optional(),
});
export const graphDataSchema = z.object({
  nodes: z.array(graphNodeSchema),
  edges: z.array(graphEdgeSchema),
});
export const graphStatsSchema = z.object({
  nodes: z.number().int(),
  edges: z.number().int(),
  last_query_ms: z.number(),
});
export const agentScreenSchema = z.object({
  url: z.string().nullable(),
  caption: z.string(),
  mock: z.boolean().default(false),
});
export const ingestProgressSchema = z.object({
  emails_scanned: z.number().int(),
  accounts_found: z.number().int(),
  edges_inferred: z.number().int(),
  edges_confirmed: z.number().int(),
  status: z.enum(["idle", "running", "done"]),
});
export const onboardingRequestSchema = z.object({
  inboxes: z.array(
    z.object({
      host: z.string().min(1),
      username: z.string().min(1),
      app_password: z.string().min(1),
    }),
  ),
  phones: z.array(
    z.object({
      number: z.string().min(1),
      carrier: z.string(),
      status: z.enum(["retiring", "active"]),
      drop_at: date.optional(),
      id: z.string().min(1).optional(),
      country: z.string().optional(),
    }),
  ),
  display_name: z.string().optional(),
  emails: z.array(z.object({
    id: z.string().min(1), address: z.string().min(1),
    kind: z.enum(["personal", "edu", "work", "custom"]).optional(),
    hosted_by: z.string().optional(),
    status: z.enum(["active", "closing", "closed"]).optional(),
    closes_at: date.optional(),
  })).optional(),
  devices: z.array(z.object({
    id: z.string().min(1), name: z.string().min(1),
    kind: z.enum(["phone", "laptop", "key"]),
    status: z.enum(["active", "sold", "lost"]).optional(),
  })).optional(),
});
export const chatButtonSchema = z.discriminatedUnion("action", [
  z.object({label: z.string(), action: z.literal("open_web"), payload: z.object({path: z.string()})}),
  z.object({label: z.string(), action: z.literal("plan_root"), payload: z.object({root_id: z.string()})}),
  z.object({label: z.string(), action: z.literal("approve_changes"), payload: z.object({change_ids: z.array(z.string()), approval_token: z.string().optional()})}),
]);
export const chatReplySchema = z.object({
  text: z.string(), buttons: z.array(chatButtonSchema), tool_calls: z.array(z.string()),
});
export type ChatReply = z.infer<typeof chatReplySchema>;
export type ChatButton = z.infer<typeof chatButtonSchema>;
export const onboardingResultSchema = z.object({
  telegram_code: z.string(),
  telegram_url: z.string(),
});
export const ingestRunSchema = z.object({ started: z.boolean() });

export type Root = z.infer<typeof rootSchema>;
export type Account = z.infer<typeof accountSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Reached = z.infer<typeof reachedSchema>;
export type ScenarioResult = z.infer<typeof scenarioResultSchema>;
export type ScenarioRequest = z.infer<typeof scenarioRequestSchema>;
export type PathStep = z.infer<typeof pathStepSchema>;
export type Explanation = z.infer<typeof explanationSchema>;
export type Change = z.infer<typeof changeSchema>;
export type Plan = z.infer<typeof planSchema>;
export type PlanRequest = z.infer<typeof planRequestSchema>;
export type ExecStep = z.infer<typeof execStepSchema>;
export type Signal = z.infer<typeof signalSchema>;
export type ToolCallRecord = z.infer<typeof toolCallRecordSchema>;
export type GraphEvent = z.infer<typeof graphEventSchema>;
export type GraphNode = z.infer<typeof graphNodeSchema>;
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export type GraphData = z.infer<typeof graphDataSchema>;
export type GraphStats = z.infer<typeof graphStatsSchema>;
export type AgentScreen = z.infer<typeof agentScreenSchema>;
export type IngestProgress = z.infer<typeof ingestProgressSchema>;
export type OnboardingRequest = z.infer<typeof onboardingRequestSchema>;
export type OnboardingResult = z.infer<typeof onboardingResultSchema>;
export type UiEvent =
  | { kind: "scenario"; data: ScenarioResult }
  | { kind: "plan"; data: Plan }
  | { kind: "exec"; data: ExecStep }
  | { kind: "trace"; data: ToolCallRecord }
  | { kind: "ingest"; data: IngestProgress }
  | { kind: "stats"; data: GraphStats }
  | { kind: "signal"; data: Signal }
  | { kind: "other"; data: GraphEvent };

export function decodeEvent(event: GraphEvent): UiEvent {
  switch (event.type) {
    case "scenario":
      return { kind: "scenario", data: scenarioResultSchema.parse(event.data) };
    case "plan":
      return { kind: "plan", data: planSchema.parse(event.data) };
    case "exec":
      return { kind: "exec", data: execStepSchema.parse(event.data) };
    case "trace":
      return { kind: "trace", data: toolCallRecordSchema.parse(event.data) };
    case "ingest":
      return { kind: "ingest", data: ingestProgressSchema.parse(event.data) };
    case "signal":
      return { kind: "signal", data: signalSchema.parse(event.data) };
    case "graph": {
      const stats = graphStatsSchema.safeParse(event.data);
      return stats.success
        ? { kind: "stats", data: stats.data }
        : { kind: "other", data: event };
    }
    case "chat":
      return { kind: "other", data: event };
  }
}

export interface LapseApi {
  getRoots(): Promise<Root[]>;
  getGraph(scenario?: string): Promise<GraphData>;
  createScenario(input: ScenarioRequest): Promise<ScenarioResult>;
  getScenario(id: string): Promise<ScenarioResult>;
  explain(scenarioId: string, accountId: string): Promise<Explanation>;
  createPlan(input: PlanRequest): Promise<Plan>;
  getPlan(id: string): Promise<Plan>;
  getPlans(): Promise<Plan[]>;
  chat(text: string): Promise<ChatReply>;
  approveChange(id: string): Promise<Change>;
  submitOtp(id: string, code: string): Promise<Change>;
  getTrace(since?: string): Promise<ToolCallRecord[]>;
  getScreen(): Promise<AgentScreen>;
  getStats(): Promise<GraphStats>;
  onboard(input: OnboardingRequest): Promise<OnboardingResult>;
  runIngest(inboxes?: string[]): Promise<{ started: boolean }>;
  subscribe(
    onEvent: (event: UiEvent) => void,
    onError?: (error: Error) => void,
    onReconnect?: () => void,
  ): () => void;
}
