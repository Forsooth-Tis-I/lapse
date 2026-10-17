"""Exercise the seeded demo over HTTP; --chat makes six real configured-provider requests."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx

PROMPTS = [
    "what happens if someone gets my old number?",
    "why is dropbox at risk?",
    "what do I lose when my college email closes?",
    "plan the fix for my old number",
    "is splitwise safe?",
    "approve",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".audit/wave2-smoke.json"))
    args = parser.parse_args()
    report = {"scenarios": [], "explanations": [], "plans": [], "chat": []}
    with httpx.Client(base_url=args.base_url, headers={"X-Lapse-Uid": "demo"}, timeout=180) as client:
        for kind, roots in [
            ("takeover", ["phone_old"]),
            ("lockout", ["email_college"]),
            ("lockout", ["phone_old", "email_college"]),
        ]:
            response = client.post("/api/scenarios", json={"kind": kind, "root_ids": roots})
            response.raise_for_status()
            report["scenarios"].append(response.json())
        scenario_id = report["scenarios"][0]["id"]
        for account, status in [("dropbox", 200), ("splitwise", 404)]:
            response = client.get(f"/api/scenarios/{scenario_id}/explain/{account}")
            assert response.status_code == status, (account, response.status_code)
            report["explanations"].append({"account": account, "status": status, "result": response.json()})
        for old, new in [("phone_old", "phone_new"), ("email_college", "email_primary")]:
            response = client.post("/api/plans", json={"old_root": old, "new_root": new})
            response.raise_for_status()
            plan = response.json()
            assert plan["exposure_after"] == 0, plan["note"]
            assert len({s["account_id"] for s in plan["steps"]}) == len(plan["steps"])
            report["plans"].append(plan)
            print(old, plan["exposure_before"], "->", plan["exposure_after"], flush=True)
        if args.chat:
            for prompt in PROMPTS:
                start = perf_counter()
                response = client.post("/api/chat", json={"text": prompt})
                elapsed = perf_counter() - start
                response.raise_for_status()
                reply = response.json()
                report["chat"].append(
                    {
                        "prompt": prompt,
                        "seconds": round(elapsed, 3),
                        "text": reply["text"],
                        "tool_calls": reply["tool_calls"],
                        "diagnostics": reply.get("diagnostics", {}),
                        "buttons": [button["label"] for button in reply["buttons"]],
                    }
                )
                print(json.dumps(report["chat"][-1]), flush=True)
        response = client.get("/api/trace")
        response.raise_for_status()
        report["trace_count"] = len(response.json())
        response = client.get("/api/stats")
        response.raise_for_status()
        report["stats"] = response.json()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Saved", args.output, flush=True)


if __name__ == "__main__":
    main()
