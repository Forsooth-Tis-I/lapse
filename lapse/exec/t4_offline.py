import json
from datetime import UTC, datetime, time, timedelta

from lapse.contracts import Change
from lapse.exec.base import ExecContext, redis_client
from lapse.graph import db

REMINDERS = "lapse:exec:reminders"


class OfflineExecutor:
    def can_run(self, change: Change) -> bool:
        return change.tier == 4

    async def run(self, ctx: ExecContext) -> bool:
        target = ctx.new_root.label if ctx.new_root else "remove the old contact"
        text = (
            f"Checklist for {ctx.service.name}:\n"
            "1. Check the provider's official document requirements.\n"
            "2. Bring identity proof, account details and access to the new contact.\n"
            "3. Submit the contact-update form and keep the receipt.\n"
            "4. Verify that the old contact is removed.\n\n"
            f"Draft request: Please update the {ctx.change.role.value} on my account "
            f"from {ctx.old_root.label} to {target}. Please confirm completion in writing.\n"
            "Account reference: [fill in locally]. Name and signature: [fill in locally]."
        )
        ctx.emitter.emit("need_user", text, url=ctx.procedure.doc_url)
        due = datetime.now(UTC) + timedelta(days=1)
        if ctx.change.due:
            due = min(due, datetime.combine(ctx.change.due, time(9), tzinfo=UTC))
        redis_client().zadd(REMINDERS, {json.dumps([ctx.uid, ctx.change.id]): due.timestamp()})
        return False


def send_due_reminders(*, trace=None) -> int:
    from lapse.notify import notify

    redis = redis_client()
    sent = 0
    for member in redis.zrangebyscore(REMINDERS, "-inf", datetime.now(UTC).timestamp()):
        uid, change_id = json.loads(member)
        rows = db.run(db.user_graph(uid), "planner_get_change", {"change_id": change_id}, trace=trace).rows
        if not rows or rows[0]["change"]["status"] in {"done", "skipped", "failed"}:
            redis.zrem(REMINDERS, member)
            continue
        notify(
            uid, f"Reminder: complete the offline contact change for {rows[0]['change']['account_label']}."
        )
        redis.zadd(REMINDERS, {member: (datetime.now(UTC) + timedelta(days=1)).timestamp()})
        sent += 1
    return sent


def register_reminders(scheduler) -> None:
    scheduler.add_job(send_due_reminders, "interval", seconds=60, id="exec_reminders", replace_existing=True)
