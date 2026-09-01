from smartdialer.engine.context import DialerContext


class ProgressivePacingEngine:
    """
    Progressive mode:
    One available agent -> at most one agent-bound outbound call.
    """

    def compute_desired_calls(self, ctx: DialerContext) -> int:
        if ctx.available_agents <= 0 or ctx.queued_borrowers <= 0:
            return 0

        desired = ctx.available_agents - ctx.active_agent_calls
        return max(0, min(desired, ctx.queued_borrowers))