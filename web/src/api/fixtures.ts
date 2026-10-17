import {
  accountSchema,
  rootSchema,
  type Evidence,
  type GraphData,
  type GraphEdge,
  type GraphNode,
} from "./contracts";

export const roots = [
  rootSchema.parse({
    id: "phone_old",
    kind: "phone",
    label: "••4321 (Vi)",
    status: "retiring",
    last4: "4321",
    carrier: "Vi",
    country: "IN",
    drop_at: "2026-10-31",
    reissue_after: "2027-01-29",
  }),
  rootSchema.parse({
    id: "phone_new",
    kind: "phone",
    label: "••7788 (Jio)",
    last4: "7788",
    carrier: "Jio",
    country: "IN",
  }),
  rootSchema.parse({
    id: "email_primary",
    kind: "email",
    label: "Primary Gmail",
    email_kind: "personal",
    hosted_by_service: "google",
  }),
  rootSchema.parse({
    id: "email_college",
    kind: "email",
    label: "College inbox",
    email_kind: "edu",
    hosted_by_service: "college_workspace",
    status: "closing",
    closes_at: "2026-11-15",
  }),
  rootSchema.parse({
    id: "device_phone",
    kind: "device",
    label: "Authenticator",
    device_kind: "phone",
  }),
];
const services: [string, string][] = [
  ["google", "Google"],
  ["college_workspace", "College Workspace"],
  ["notion", "Notion"],
  ["spotify", "Spotify"],
  ["x", "X"],
  ["amazon_in", "Amazon India"],
  ["swiggy", "Swiggy"],
  ["zomato", "Zomato"],
  ["paypal", "PayPal"],
  ["dropbox", "Dropbox"],
  ["github", "GitHub"],
  ["linkedin", "LinkedIn"],
  ["figma", "Figma"],
  ["canva", "Canva"],
  ["coursera", "Coursera"],
  ["microsoft", "Microsoft"],
  ["splitwise", "Splitwise"],
];
export const accounts = services.map(([id, display]) =>
  accountSchema.parse({
    id,
    service_id: id,
    display,
    modelled: id !== "splitwise",
    first_seen: "2024-09-03T10:00:00Z",
    last_seen: "2026-10-16T09:15:00Z",
  }),
);
export const directIds = ["google", "x", "amazon_in", "swiggy", "zomato"];
export const downstreamIds = [
  "notion",
  "spotify",
  "paypal",
  "dropbox",
  "linkedin",
];
export const collegeIds = ["figma", "canva", "coursera", "microsoft"];
const edge = (
  source: string,
  target: string,
  label: string,
  confirmed = true,
): GraphEdge => ({
  id: `${source}:${target}`,
  source,
  target,
  label,
  confirmed,
  method_id:
    target === "dropbox"
      ? "dropbox:email_and_sms"
      : target === "github"
        ? "github:email_and_totp"
        : `${target}:${label.toLowerCase().replaceAll(" ", "_")}`,
});
export const initialGraph: GraphData = {
  nodes: [
    ...roots.map((root): GraphNode => ({
      id: root.id,
      label: root.label,
      node_type: "Root",
      root,
    })),
    ...accounts.map((account): GraphNode => ({
      id: account.id,
      label: account.display,
      node_type: "Account",
      account,
    })),
  ],
  edges: [
    ...directIds.map((id) => edge("phone_old", id, "SMS recovery")),
    edge("google", "email_primary", "Hosts mailbox"),
    ...downstreamIds.map((id) =>
      edge(
        "email_primary",
        id,
        id === "dropbox" ? "Email AND SMS" : "Email reset",
      ),
    ),
    edge("phone_old", "dropbox", "SMS AND email"),
    edge("email_primary", "github", "Email AND TOTP"),
    edge("device_phone", "github", "TOTP AND email"),
    ...collegeIds.map((id) => edge("email_college", id, "Email sign-in")),
    edge("email_college", "google", "Backup recovery"),
    edge("college_workspace", "email_college", "Hosts mailbox"),
    edge("phone_old", "splitwise", "Unconfirmed contact", false),
  ],
};
export function label(id: string): string {
  return initialGraph.nodes.find((node) => node.id === id)?.label ?? id;
}
export function evidence(accountId: string): Evidence {
  const accountLabel = label(accountId);
  return {
    id: `evidence:${accountId}`,
    msg_id: `demo-${accountId}-20261012`,
    inbox: collegeIds.includes(accountId) ? "email_college" : "email_primary",
    date: "2026-10-12T08:40:00Z",
    sender: `security@${accountId === "google" ? "google.com" : `${accountId.replace("_in", "")}.com`}`,
    subject:
      accountId === "google"
        ? "Recovery phone ending in 4321 added"
        : `${accountLabel}: confirm your recovery details`,
    snippet:
      "Demo evidence: your account recovery details were confirmed. Header and short excerpt only.",
    event: "verify_email",
  };
}
