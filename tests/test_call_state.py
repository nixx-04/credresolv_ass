import pytest

from smartdialer.db import async_session_maker
from smartdialer.models import Agent, Call, Campaign
from smartdialer.services import process_event
from smartdialer.states import AgentState, CallState


async def seed_call(
    session,
    call_state: str = CallState.RINGING,
    attach_agent: bool = True,
) -> str:
    campaign = Campaign(
        name="State Test",
        mode="predictive",
        active=True,
    )
    session.add(campaign)
    await session.flush()

    agent = None

    if attach_agent:
        agent = Agent(
            campaign_id=campaign.id,
            state=AgentState.DIALING,
        )
        session.add(agent)
        await session.flush()

    call = Call(
        campaign_id=campaign.id,
        agent_id=agent.id if agent else None,
        state=call_state,
        provider="provider_a",
        idempotency_key=f"call-test-{call_state}",
    )
    session.add(call)
    await session.commit()

    return call.id


@pytest.mark.asyncio
async def test_duplicate_answered_event_is_ignored(session):
    call_id = await seed_call(session, CallState.RINGING, attach_agent=True)

    payload = {
        "event_id": "event-1",
        "call_id": call_id,
        "event_type": "ANSWERED",
    }

    first = await process_event(async_session_maker, payload)
    second = await process_event(async_session_maker, payload)

    assert first["status"] == "ok"
    assert second["status"] == "duplicate"


@pytest.mark.asyncio
async def test_out_of_order_completed_then_answered(session):
    call_id = await seed_call(session, CallState.INITIATED, attach_agent=True)

    completed_payload = {
        "event_id": "event-completed",
        "call_id": call_id,
        "event_type": "COMPLETED",
    }

    answered_payload = {
        "event_id": "event-answered",
        "call_id": call_id,
        "event_type": "ANSWERED",
    }

    completed_result = await process_event(async_session_maker, completed_payload)
    answered_result = await process_event(async_session_maker, answered_payload)

    assert completed_result["status"] == "ok"
    assert answered_result["status"] == "invalid_transition"