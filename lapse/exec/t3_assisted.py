from lapse.contracts import Change
from lapse.exec.base import ExecContext


class AssistedExecutor:
    def can_run(self, change: Change) -> bool:
        return True

    async def run(self, ctx: ExecContext, *, url: str | None = None) -> bool:
        target = ctx.new_root.label if ctx.new_root else "remove the old contact"
        message = (
            f"Open {ctx.service.name} settings and change {ctx.change.role.value} from "
            f"{ctx.old_root.label} to {target}. Remove the old contact after verifying the new one. "
            "I will watch for a matching confirmation email."
        )
        ctx.emitter.emit(
            "need_user", message, url=url or ctx.procedure.settings_url or ctx.change.settings_url
        )
        return False
