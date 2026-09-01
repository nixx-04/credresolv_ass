import asyncio

import pytest

from smartdialer.allocator.call_allocator import reserve_available_agent
from smartdialer.db import async_session_maker
from smartdialer.models import Agent, Campaign
from smartdialer.states import AgentState


@pytest.mark.asyncio
async def test_two_workers_cannot_reserve_same_agent(session):
    campaign = Campaign(
        name="Concurrency",
        mode="progressive",
        active=True,
    )
    session.add(campaign)
    await session.flush()

    session.add(
        Agent(
            campaign_id=campaign.id,
            state=AgentState.AVAILABLE,
        )
    )

    await session.commit()

    campaign_id = campaign.id

    async def attempt_reserve() -> str | None:
        async with async_session_maker() as worker_session:
            async with worker_session.begin():
                return await reserve_available_agent(worker_session, campaign_id)

    results = await asyncio.gather(
        attempt_reserve(),
        attempt_reserve(),
    )

    successful = [agent_id for agent_id in results if agent_id is not None]

    assert len(successful) == 1