from smartdialer.engine.context import DialerContext


class PredictivePacingEngine:
    """
    Simple predictive pacing.

    The pacing engine only answers:
    "I would like to start N calls."

    It never calls the telecom provider directly.
    """

    def compute_desired_calls(self, ctx: DialerContext) -> int:
        if ctx.available_agents <= 0 or ctx.queued_borrowers <= 0:
            return 0

        answer_rate = max(ctx.answer_rate, 0.01)

        # Agents we still need to keep busy.
        headroom = ctx.available_agents - ctx.active_connections
        if headroom <= 0:
            return 0

        # Calls already ringing are expected to consume some agent capacity.
        expected_connects_in_flight = ctx.ringing_calls * ctx.answer_rate
        effective_headroom = headroom - expected_connects_in_flight

        if effective_headroom <= 0:
            return 0

        desired = effective_headroom / answer_rate
        desired *= max(ctx.overdial_factor, 1.0)

        return max(0, min(int(desired), ctx.queued_borrowers))