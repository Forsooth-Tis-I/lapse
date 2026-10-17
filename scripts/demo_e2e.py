"""Run a local fixture simulation. No real browser, inbox, OTP or notifications."""

from __future__ import annotations

import json
import os
import socket
from collections import Counter
from contextlib import ExitStack, asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from importlib import import_module
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import load_fixture
from playwright import async_api

from lapse import approvals, jobs, otp, worker
from lapse.config import ROOT_DIR
from lapse.contracts import ChangeStatus, Evidence, ScenarioRequest
from lapse.exec import base, browser, inbox_codes
from lapse.exec.verify import verify_pending
from lapse.graph import db, planner, scenarios, views
from lapse.policy.loader import default_policy_paths, load_policy_file
from lapse.signals import detectors

UID = "demo"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class SimulatedLocator:
    def __init__(self, page, name):
        self.page, self.name = page, name

    async def wait_for(self, *, state, timeout):
        if self.name in {self.page.old, self.page.new}:
            visible = (self.name == self.page.new) == self.page.saved
            require(visible == (state == "visible"), "Simulated contact assertion failed")

    async def count(self):
        return 1

    async def click(self, **kwargs):
        if self.name in {"Confirm", "Verify"} and self.page.replacement_entered:
            self.page.saved = True

    async def fill(self, value, **kwargs):
        if value == self.page.new:
            self.page.replacement_entered = True

    def filter(self, **kwargs):
        return self

    def get_by_role(self, role, *, name, exact=True):
        return SimulatedLocator(self.page, name)

    def get_by_text(self, text, *, exact=True):
        return SimulatedLocator(self.page, text)


class SimulatedPage:
    def __init__(self, old, new, domains):
        self.old, self.new, self.domains = old, new, domains
        self.replacement_entered = self.saved = False

    async def goto(self, url):
        require(browser.navigation_allowed(url, self.domains), "Unexpected simulated navigation")

    def get_by_role(self, role, *, name=None, exact=True):
        return SimulatedLocator(self, name)

    def get_by_text(self, text, *, exact=True):
        return SimulatedLocator(self, text)


def main():
    print("SIMULATION ONLY: resets lapse:u:demo; browser, inbox, OTP and delivery are synthetic.")
    started = perf_counter()
    redis = fakeredis.FakeRedis(decode_responses=True)
    queries, notifications, events = [], [], []
    activity = Counter()
    contacts = {}
    original_run, original_connect, original_connect_ex = (
        db.run,
        socket.socket.connect,
        socket.socket.connect_ex,
    )

    def traced_run(*args, **kwargs):
        original_trace = kwargs.pop("trace", None)

        def record(name, params, ms, rows):
            queries.append((name, ms, rows))
            if original_trace:
                original_trace(name, params, ms, rows)

        return original_run(*args, trace=record, **kwargs)

    @contextmanager
    def stage(label):
        before, begin = len(queries), perf_counter()
        yield
        print(f"{label}: {(perf_counter() - begin) * 1000:.0f} ms; trace queries={len(queries) - before}")

    def local_connection(connect):
        def guarded(sock, address):
            require(
                isinstance(address, tuple)
                and address[0] in {"localhost", "127.0.0.1", "::1"}
                and address[1] == 6380,
                "Simulation blocked a connection outside local FalkorDB",
            )
            return connect(sock, address)

        return guarded

    def forbidden(*args, **kwargs):
        raise RuntimeError("Real browser or inbox access is disabled in this simulation")

    @asynccontextmanager
    async def simulated_browser(uid, service, domains):
        require(uid == UID and service in contacts, "Unexpected simulated browser request")
        page = SimulatedPage(*contacts[service], domains)

        async def new_page():
            return page

        activity[f"browser_{service}"] += 1
        yield SimpleNamespace(new_page=new_page)
        require(page.saved, "Simulated browser did not save its replacement contact")

    async def simulated_inbox(*args, **kwargs):
        activity["inbox_proofs"] += 1
        return "654321"

    async def simulated_screenshot(*args, **kwargs):
        activity["screenshots"] += 1
        return "simulation:no-file"

    with ExitStack() as stack:
        for owner, name, replacement in (
            (db, "run", traced_run),
            (views, "run", traced_run),
            (import_module("lapse.policy.compile"), "run", traced_run),
            (load_fixture, "run", traced_run),
            (jobs, "client", lambda: redis),
            (base, "redis_client", lambda: redis),
            (approvals, "settings", lambda: SimpleNamespace(approval_signing_key="simulation-only-key")),
            (browser, "open_browser", simulated_browser),
            (browser, "follow_verification_link", forbidden),
            (async_api, "async_playwright", forbidden),
            (inbox_codes, "await_inbox_code", simulated_inbox),
            (inbox_codes, "IMAPClient", forbidden),
            (base.StepEmitter, "screenshot", simulated_screenshot),
            (detectors, "rdap_expiry", lambda *args, **kwargs: None),
            (socket.socket, "connect", local_connection(original_connect)),
            (socket.socket, "connect_ex", local_connection(original_connect_ex)),
        ):
            stack.enter_context(patch.object(owner, name, replacement))
        stack.enter_context(patch.dict(os.environ, {"HANDLER_MODULES": "lapse.exec.jobs,lapse.signals.jobs"}))
        subscriber = stack.enter_context(redis.pubsub(ignore_subscribe_messages=True))
        subscriber.subscribe(f"lapse:notify:{UID}", f"lapse:events:{UID}")
        for _ in range(2):
            subscriber.get_message()

        def drain():
            while message := subscriber.get_message():
                payload = json.loads(message["data"])
                if message["channel"] == f"lapse:notify:{UID}":
                    require(set(payload) == {"text", "buttons"}, "Incorrect notify payload")
                    notifications.append(payload)
                else:
                    events.append(payload)

        with stage("1. Public fixture loaded"):
            g = db.user_graph(UID)
            require(g.name == "lapse:u:demo", "Only the demo graph may be reset")
            policies, carriers = [], []
            for path in default_policy_paths():
                loaded, rules = load_policy_file(path)
                policies.extend(loaded)
                carriers.extend(rules)
            load_fixture._drop(g)
            load_fixture.load_persona(g, policies, carriers, ROOT_DIR / "fixtures/persona.yaml")
            db.run(
                g,
                "demo_phone_values",
                {
                    "phones": [
                        {"id": "phone_old", "e164": "+15550004321"},
                        {"id": "phone_new", "e164": "+15550007788"},
                    ]
                },
                write=True,
            )
            roots = {row["root"]["id"]: row["root"] for row in db.run(g, "view_roots").rows}
            contacts.update(
                x=(roots["phone_old"]["e164"], roots["phone_new"]["e164"]),
                canva=(roots["email_college"]["address"], roots["email_primary"]["address"]),
            )
            worker.load_handlers()

        with stage("2. Detectors raised reissue and closing signals; notify payloads captured"):
            signals = worker.dispatch_job(UID, "run_detectors", {"now": "2026-10-17"})
            require({"reissue_countdown", "closing_email"} <= {s.kind for s in signals}, "Signals missing")
            drain()
            require(len(notifications) >= 2, "Detector notifications missing")
            print(f"   signals={len(signals)}; notify payloads={len(notifications)}; delivery=FakeRedis only")

        with stage("3. Phone fix plan and Canva T1 step built"):
            phone_plan = planner.plan_for_root(UID, "phone_old", "phone_new")
            email_plan = planner.plan_for_root(UID, "email_college", "email_primary")
            canva = next(step for step in email_plan.steps if step.account_id == "canva")
            selected = [*phone_plan.steps, canva]
            require(canva.tier == 1 and any(s.tier == 2 for s in selected), "Browser tiers missing")
            require(phone_plan.exposure_after == 0, "Phone plan leaves modeled exposure")
            print(
                f"   phone steps={len(phone_plan.steps)}; projected exposure={phone_plan.exposure_before}->0"
            )

        with stage("4. Approval minted, consumed once, and execute_change jobs queued"):
            token = approvals.mint(UID, [step.id for step in selected])
            approved = approvals.consume(UID, token)
            try:
                approvals.consume(UID, token)
            except ValueError:
                pass
            else:
                raise RuntimeError("Approval token was reusable")
            token = None
            require(approved == [step.id for step in selected], "Approval scope changed")
            for step in selected:
                planner.update_change(UID, step.id, status=ChangeStatus.approved)
                if step.tier == 2:
                    otp.submit(UID, step.id, "654321")
                jobs.enqueue(UID, "execute_change", {"change_id": step.id})

        with stage("5. Worker dispatched real handlers with simulated T1/T2 browser"):
            consumer = jobs.consume(group="demo-simulation")
            results = []
            for _ in selected:
                job = next(consumer)
                results.append(worker.dispatch_job(job.uid, job.kind, job.payload))
                job.ack()
            consumer.close()
            statuses = {result["change_id"]: result["status"] for result in results}
            for step in selected:
                expected = "done" if step.tier in {1, 2} else "awaiting_user"
                require(statuses[step.id] == expected, f"Unexpected status for {step.account_id}")
            drain()
            require(activity["browser_x"] == activity["browser_canva"] == 1, "Browser paths not exercised")
            require(activity["inbox_proofs"] == 2, "Canva must prove both inboxes")
            require(
                any(
                    e["type"] == "exec"
                    and e["data"]["kind"] == "need_otp"
                    and e["data"]["channel"].startswith("sms:")
                    for e in events
                ),
                "OTP event missing",
            )
            counts = Counter(statuses.values())
            print(
                f"   done={counts['done']}; awaiting_user={counts['awaiting_user']}; synthetic inbox proofs=2"
            )

        def exposure():
            return {
                account.node_id
                for kind in ("takeover", "lockout")
                for account in scenarios.run_scenario(
                    UID, ScenarioRequest(kind=kind, root_ids=["phone_old"])
                ).affected_accounts
            }

        with stage("6. Synthetic confirmation verified T3, repointed USES, and recomputed exposure"):
            assisted = next(
                step for step in phone_plan.steps if step.account_id == "google" and step.tier == 3
            )
            before = exposure()
            require(verify_pending(UID) == [], "A T3 change completed without new evidence")
            pending = next(
                row for row in db.run(g, "exec_pending").rows if row["change"]["id"] == assisted.id
            )
            evidence = Evidence(
                id="evidence:demo:synthetic-confirmation",
                msg_id="<simulation@lapse.example>",
                inbox="email_primary",
                date=datetime.fromisoformat(pending["change"]["started_at"]) + timedelta(seconds=1),
                sender="simulation@accounts.google.com",
                subject="Recovery phone has been changed",
                snippet="SIMULATION: Your recovery phone has been changed from ending 4321 to ending 7788.",
                event="contact_changed",
            )
            db.run(
                g,
                "fixture_evidence",
                {
                    "props": evidence.model_dump(mode="json"),
                    "account_id": assisted.account_id,
                    "root_ids": ["phone_new"],
                },
                write=True,
            )
            require(
                verify_pending(UID) == [assisted.id], "Synthetic confirmation did not close the T3 change"
            )
            uses = db.run(g, "view_uses", {"account_id": assisted.account_id}).rows
            for role in assisted.roles or [assisted.role]:
                require(
                    any(u["role"] == role and u["root_id"] == "phone_new" for u in uses), "USES not repointed"
                )
                require(
                    not any(u["role"] == role and u["root_id"] == "phone_old" for u in uses),
                    "Old USES remains",
                )
            after = exposure()
            require(after < before, "Confirmed T3 change did not reduce combined exposure")
            drain()
            print(
                f"   T3 account={assisted.account_id}; status=done; actual combined exposure={len(before)}->{len(after)}"
            )

    print(
        f"SIMULATION PASS: {len(queries)} trace queries; {len(notifications)} captured notifications; "
        f"{(perf_counter() - started):.2f}s. Remaining T3 steps await the user; no real accounts touched."
    )


if __name__ == "__main__":
    main()
