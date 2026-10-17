import type { ScenarioResult } from "../api";

export function LockoutSummary({ results }: { results: ScenarioResult[] }) {
  const lockouts = results.filter((result) => result.kind === "lockout");
  if (lockouts.length === 0) return null;
  const lostNow = new Map(lockouts.flatMap((result) =>
    (result.lost_now_accounts ?? result.affected_accounts)
      .filter((account) => account.node_type === "Account")
      .map((account) => [account.node_id, account.label] as const),
  ));
  const recoveryReported = lockouts.every((result) => result.recovery_lost_accounts !== undefined);
  const recoveryLost = new Map(lockouts.flatMap((result) =>
    (result.recovery_lost_accounts ?? [])
      .filter((account) => account.node_type === "Account")
      .map((account) => [account.node_id, account.label] as const),
  ));
  return (
    <div className="lockout-summary" aria-label="Lockout summary">
      <div>
        <strong>{lostNow.size} lost now</strong>
        <span>{lostNow.size ? [...lostNow.values()].join(", ") : "No fresh sign-in lockouts returned. Password login can still work when you know the password."}</span>
      </div>
      <div>
        <strong>{recoveryReported ? `${recoveryLost.size} with recovery lost` : "Recovery loss not reported"}</strong>
        <span>{recoveryReported
          ? `No way back if you forget the password${recoveryLost.size ? `: ${[...recoveryLost.values()].join(", ")}` : ": no accounts returned"}.`
          : "The API has not assessed the separate risk of forgetting your password."}</span>
      </div>
    </div>
  );
}
