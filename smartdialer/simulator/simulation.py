import asyncio

from sqlalchemy import text

from smartdialer.db import async_session_maker, reset_db
from smartdialer.models import Agent, Borrower, Campaign
from smartdialer.providers.provider_a import ProviderA
from smartdialer.providers.provider_b import ProviderB
from smartdialer.providers.registry import ProviderRegistry
from smartdialer.services import process_event
from smartdialer.states import AgentState, BorrowerState
from smartdialer.workers.dialer_worker import DialerWorker


async def seed_campaign(
    mode: str,
    answer_rate: float,
    talk_time_sec: int,
    agents: int = 10,
    borrowers: int = 80,
) -> str:
    async with async_session_maker() as session:
        async with session.begin():
            campaign = Campaign(
                name=f"Scenario {answer_rate:.0%}",
                mode=mode,
                answer_rate=answer_rate,
                avg_talk_time_sec=talk_time_sec,
                avg_wrap_time_sec=0,
                overdial_factor=1.0,
                active=True,
            )
            session.add(campaign)
            await session.flush()

            for _ in range(agents):
                session.add(
                    Agent(
                        campaign_id=campaign.id,
                        state=AgentState.AVAILABLE,
                    )
                )

            for i in range(borrowers):
                session.add(
                    Borrower(
                        campaign_id=campaign.id,
                        phone=f"+1555{i:04d}",
                        state=BorrowerState.PENDING,
                    )
                )

            campaign_id = campaign.id

    return campaign_id


def make_event_callback(registry: ProviderRegistry):
    async def callback(payload: dict) -> None:
        await process_event(
            async_session_maker,
            payload,
            registry,
        )

    return callback


async def print_stats(campaign_id: str, label: str) -> None:
    async with async_session_maker() as session:
        agent_rows = (
            await session.execute(
                text(
                    """
                    SELECT state, COUNT(*)
                    FROM agents
                    WHERE campaign_id = :campaign_id
                    GROUP BY state
                    """
                ),
                {"campaign_id": campaign_id},
            )
        ).fetchall()

        call_rows = (
            await session.execute(
                text(
                    """
                    SELECT state, COUNT(*)
                    FROM calls
                    WHERE campaign_id = :campaign_id
                    GROUP BY state
                    """
                ),
                {"campaign_id": campaign_id},
            )
        ).fetchall()

        total_agents = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM agents
                WHERE campaign_id = :campaign_id
                """
            ),
            {"campaign_id": campaign_id},
        )

        completed_calls = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM calls
                WHERE campaign_id = :campaign_id
                  AND state = 'COMPLETED'
                """
            ),
            {"campaign_id": campaign_id},
        )

        abandoned_calls = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM calls
                WHERE campaign_id = :campaign_id
                  AND failure_reason = 'ABANDONED'
                """
            ),
            {"campaign_id": campaign_id},
        )

        initiated_calls = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM calls
                WHERE campaign_id = :campaign_id
                  AND state NOT IN ('QUEUED', 'RESERVED')
                """
            ),
            {"campaign_id": campaign_id},
        )

        connected_calls = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM calls
                WHERE campaign_id = :campaign_id
                  AND state IN ('ANSWERED', 'CONNECTED', 'COMPLETED')
                """
            ),
            {"campaign_id": campaign_id},
        )

    utilization = completed_calls / max(1, total_agents)

    print(f"\n=== Scenario {label} ===")
    print("Agents:", dict(agent_rows))
    print("Calls:", dict(call_rows))
    print("Initiated calls:", initiated_calls)
    print("Connected calls:", connected_calls)
    print("Completed calls:", completed_calls)
    print("Abandoned calls:", abandoned_calls)
    print("Calls completed per agent:", f"{utilization:.2f}")


async def run_scenario(
    label: str,
    answer_rate: float,
    talk_time_sec: int,
    mode: str = "predictive",
    ticks: int = 25,
) -> None:
    await reset_db()

    campaign_id = await seed_campaign(
        mode=mode,
        answer_rate=answer_rate,
        talk_time_sec=talk_time_sec,
        agents=10,
        borrowers=100,
    )

    registry = ProviderRegistry()
    callback = make_event_callback(registry)

    # Scale talk time down so simulation finishes quickly.
    scaled_talk_time = max(0.02, talk_time_sec / 1500.0)

    provider_a = ProviderA(
        event_callback=callback,
        answer_rate=answer_rate,
        talk_time_sec=scaled_talk_time,
        failure_rate=0.0,
        latency_sec=0.01,
    )

    provider_b = ProviderB(
        event_callback=callback,
        answer_rate=answer_rate,
        talk_time_sec=scaled_talk_time,
        timeout_rate=0.0,
        latency_min_sec=0.01,
        latency_max_sec=0.04,
    )

    registry.add_provider(provider_a)
    registry.add_provider(provider_b)

    worker = DialerWorker(
        session_maker=async_session_maker,
        provider_registry=registry,
    )

    decisions = []

    for i in range(ticks):
        result = await worker.run_campaign_tick(campaign_id)
        if result and "requested" in result:
            decisions.append(result)

        if label == "D" and i == ticks // 2:
            new_answer_rate = 0.10 if answer_rate > 0.30 else 0.70
            provider_a.answer_rate = new_answer_rate
            provider_b.answer_rate = new_answer_rate

            async with async_session_maker() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            UPDATE campaigns
                            SET answer_rate = :answer_rate
                            WHERE id = :campaign_id
                            """
                        ),
                        {
                            "answer_rate": new_answer_rate,
                            "campaign_id": campaign_id,
                        },
                    )

        await asyncio.sleep(0.03)

    # Allow provider simulation tasks to finish.
    await asyncio.sleep(2.0)

    total_requested = sum(d.get("requested", 0) for d in decisions)
    total_approved = sum(d.get("approved", 0) for d in decisions)
    total_initiated = sum(d.get("initiated", 0) for d in decisions)

    print(f"\nScenario {label} pacing decisions")
    print("Requested:", total_requested)
    print("Approved:", total_approved)
    print("Initiated:", total_initiated)

    await print_stats(campaign_id, label)


async def main() -> None:
    scenarios = [
        ("A", 0.20, 120),
        ("B", 0.50, 90),
        ("C", 0.70, 180),
        ("D", 0.50, 120),
    ]

    for label, answer_rate, talk_time_sec in scenarios:
        await run_scenario(
            label=label,
            answer_rate=answer_rate,
            talk_time_sec=talk_time_sec,
            mode="predictive",
            ticks=25,
        )


if __name__ == "__main__":
    asyncio.run(main())