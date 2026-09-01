from smartdialer.engine.context import DialerContext


class SafetyController:
    """
    The pacing engine can request calls.
    The safety controller decides what is actually allowed.
    """

    MAX_ABANDON_RATE = 0.03
    PROVIDER_ERROR_FALLBACK = 0.35
    MAX_CALLS_PER_AGENT = 2.0

    def evaluate(self, requested: int, ctx: DialerContext) -> int:
        if requested <= 0:
            return 0

        if ctx.available_agents <= 0 or ctx.queued_borrowers <= 0:
            return 0

        # Hard compliance stop.
        if ctx.recent_abandon_rate > self.MAX_ABANDON_RATE:
            return 0

        # Progressive fallback: never allow more agent-bound calls than available agents.
        progressive_limit = max(0, ctx.available_agents - ctx.active_agent_calls)
        progressive_limit = min(progressive_limit, ctx.queued_borrowers)

        # If provider is badly failing, fall back to progressive behavior.
        if ctx.provider_error_rate > 0.5:
            return min(requested, progressive_limit)

        if ctx.mode == "progressive":
            return min(requested, progressive_limit)

        # Predictive mode.
        if ctx.answer_rate <= 0:
            return min(requested, progressive_limit)

        capacity_for_new_connections = max(0, ctx.available_agents - ctx.active_connections)
        if capacity_for_new_connections <= 0:
            return 0

        max_calls_by_answer_rate = capacity_for_new_connections / max(ctx.answer_rate, 0.01)

        # Prevent runaway overdialing.
        max_total_active_calls = max(
            0,
            int(ctx.available_agents * self.MAX_CALLS_PER_AGENT) - ctx.active_calls,
        )

        approved = min(
            requested,
            max_calls_by_answer_rate,
            ctx.queued_borrowers,
            max_total_active_calls,
        )

        # If system looks unhealthy, degrade toward progressive.
        if (
            ctx.provider_error_rate > self.PROVIDER_ERROR_FALLBACK
            or ctx.recent_abandon_rate > self.MAX_ABANDON_RATE / 2
        ):
            approved = min(approved, progressive_limit)

        return int(max(0, approved))