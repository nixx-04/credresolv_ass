from smartdialer.engine.context import DialerContext
from smartdialer.engine.safety_controller import SafetyController


def make_context(**kwargs) -> DialerContext:
    base = dict(
        campaign_id="campaign-1",
        mode="predictive",
        available_agents=10,
        active_calls=0,
        active_agent_calls=0,
        active_connections=0,
        ringing_calls=0,
        queued_borrowers=100,
        answer_rate=0.4,
        avg_talk_time_sec=120,
        avg_wrap_time_sec=10,
        overdial_factor=1.0,
        provider_error_rate=0.0,
        recent_abandon_rate=0.0,
    )
    base.update(kwargs)
    return DialerContext(**base)


def test_predictive_mode_is_capped():
    controller = SafetyController()
    ctx = make_context()

    approved = controller.evaluate(100, ctx)

    assert approved > 0
    assert approved <= 20


def test_progressive_mode_never_exceeds_available_agents():
    controller = SafetyController()
    ctx = make_context(
        mode="progressive",
        available_agents=5,
        active_agent_calls=2,
        queued_borrowers=100,
    )

    approved = controller.evaluate(100, ctx)

    assert approved == 3


def test_high_abandon_rate_stops_dialing():
    controller = SafetyController()
    ctx = make_context(recent_abandon_rate=0.05)

    approved = controller.evaluate(20, ctx)

    assert approved == 0


def test_provider_failure_falls_back_to_progressive():
    controller = SafetyController()
    ctx = make_context(
        provider_error_rate=0.7,
        available_agents=10,
        active_agent_calls=4,
    )

    approved = controller.evaluate(50, ctx)

    assert approved == 6