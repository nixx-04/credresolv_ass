import asyncio

from smartdialer.allocator.call_allocator import reserve_available_agent
from smartdialer.db import async_session_maker, reset_db
from smartdialer.models import Agent, Campaign
from smartdialer.states import AgentState


async def main() -> None:
    await reset_db()

    async with async_session_maker() as session:
        async with session.begin():
            campaign = Campaign(
                name="Load Test",
                mode="progressive",
                active=True,
            )
            session.add(campaign)
            await session.flush()

            for _ in range(10):
                session.add(
                    Agent(
                        campaign_id=campaign.id,
                        state=AgentState.AVAILABLE,
                    )
                )

            campaign_id = campaign.id

    async def reserve_worker() -> str | None:
        async with async_session_maker() as session:
            async with session.begin():
                return await reserve_available_agent(session, campaign_id)

    results = await asyncio.gather(*[reserve_worker() for _ in range(100)])

    successful = sum(1 for result in results if result is not None)

    print("Concurrent reservation attempts:", len(results))
    print("Successful agent reservations:", successful)

    # With 10 available agents and 100 concurrent workers,
    # successful reservations should be exactly 10.
    assert successful <= 10


if __name__ == "__main__":
    asyncio.run(main())