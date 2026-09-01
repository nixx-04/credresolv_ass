import logging
from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import text

from smartdialer.states import AgentState, BorrowerState, CallState

logger = logging.getLogger("smartdialer.allocator")


async def reserve_available_agent(session, campaign_id: str) -> Optional[str]:
    """
    Uses SELECT ... FOR UPDATE SKIP LOCKED.

    If two workers race for the same agent, the second worker will not see
    the row already locked by the first worker.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT id
                FROM agents
                WHERE campaign_id = :campaign_id
                  AND state = :available
                ORDER BY updated_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            {
                "campaign_id": campaign_id,
                "available": AgentState.AVAILABLE,
            },
        )
    ).first()

    if row is None:
        return None

    agent_id = row[0]

    result = await session.execute(
        text(
            """
            UPDATE agents
            SET state = :reserved,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
              AND state = :available
            """
        ),
        {
            "reserved": AgentState.RESERVED,
            "id": agent_id,
            "available": AgentState.AVAILABLE,
        },
    )

    if result.rowcount == 0:
        return None

    return agent_id


async def reserve_pending_borrower(
    session,
    campaign_id: str,
) -> Optional[Tuple[str, str]]:
    row = (
        await session.execute(
            text(
                """
                SELECT id, phone
                FROM borrowers
                WHERE campaign_id = :campaign_id
                  AND state = :pending
                ORDER BY updated_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            {
                "campaign_id": campaign_id,
                "pending": BorrowerState.PENDING,
            },
        )
    ).first()

    if row is None:
        return None

    borrower_id = row[0]
    phone = row[1]

    result = await session.execute(
        text(
            """
            UPDATE borrowers
            SET state = :reserved,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
              AND state = :pending
            """
        ),
        {
            "reserved": BorrowerState.RESERVED,
            "id": borrower_id,
            "pending": BorrowerState.PENDING,
        },
    )

    if result.rowcount == 0:
        return None

    return borrower_id, phone


async def set_agent_state(
    session,
    agent_id: Optional[str],
    to_state: str,
    from_states: list,
) -> bool:
    if not agent_id or not from_states:
        return False

    result = await session.execute(
        text(
            """
            UPDATE agents
            SET state = :to_state,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
              AND state = ANY(:from_states)
            """
        ),
        {
            "to_state": to_state,
            "id": agent_id,
            "from_states": from_states,
        },
    )

    return result.rowcount > 0


async def release_agent(session, agent_id: Optional[str]) -> None:
    if not agent_id:
        return

    await session.execute(
        text(
            """
            UPDATE agents
            SET state = :available,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
              AND state != :offline
            """
        ),
        {
            "available": AgentState.AVAILABLE,
            "id": agent_id,
            "offline": AgentState.OFFLINE,
        },
    )


async def release_borrower(session, borrower_id: Optional[str], state: str) -> None:
    if not borrower_id:
        return

    await session.execute(
        text(
            """
            UPDATE borrowers
            SET state = :state,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {
            "state": state,
            "id": borrower_id,
        },
    )


async def initiate_approved_calls(
    session_maker,
    campaign_id: str,
    approved_count: int,
    provider,
    mode: str,
) -> int:
    """
    Initiates approved calls.

    Important:
    - Agent and borrower reservation happens in a short transaction.
    - The call row is committed as INITIATED before provider events are
      likely to arrive.
    - This avoids webhook handlers seeing an uncommitted call row.
    """
    initiated = 0

    for _ in range(approved_count):
        call_id: Optional[str] = None
        agent_id: Optional[str] = None
        borrower_id: Optional[str] = None
        phone: Optional[str] = None

        async with session_maker() as session:
            async with session.begin():
                borrower = await reserve_pending_borrower(session, campaign_id)
                if borrower is None:
                    break

                borrower_id, phone = borrower

                if mode == "progressive":
                    agent_id = await reserve_available_agent(session, campaign_id)
                    if agent_id is None:
                        await release_borrower(
                            session,
                            borrower_id,
                            BorrowerState.PENDING,
                        )
                        break

                call_id = str(uuid4())

                await session.execute(
                    text(
                        """
                        INSERT INTO calls (
                            id,
                            campaign_id,
                            agent_id,
                            borrower_id,
                            state,
                            provider,
                            idempotency_key,
                            version,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :id,
                            :campaign_id,
                            :agent_id,
                            :borrower_id,
                            :state,
                            :provider,
                            :idempotency_key,
                            0,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "id": call_id,
                        "campaign_id": campaign_id,
                        "agent_id": agent_id,
                        "borrower_id": borrower_id,
                        "state": CallState.INITIATED,
                        "provider": provider.name,
                        "idempotency_key": f"call-{call_id}",
                    },
                )

                if agent_id:
                    await set_agent_state(
                        session,
                        agent_id,
                        AgentState.DIALING,
                        [AgentState.RESERVED],
                    )

        if call_id is None:
            break

        try:
            response = await provider.initiate_call(call_id, phone)
        except Exception:
            logger.exception("provider.initiate_call raised for call %s", call_id)
            response = None

        if response is not None and response.accepted:
            async with session_maker() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            UPDATE calls
                            SET provider_call_id = :provider_call_id,
                                version = version + 1,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :call_id
                            """
                        ),
                        {
                            "provider_call_id": response.provider_call_id,
                            "call_id": call_id,
                        },
                    )
            initiated += 1
        else:
            logger.warning(
                "provider %s rejected call %s: %s",
                provider.name,
                call_id,
                getattr(response, "error", "NO_RESPONSE"),
            )

            # If the provider rejects the call, we must fail the call and
            # release the reserved borrower (and agent, in progressive mode),
            # otherwise resources stay locked and pacing sees phantom load.
            async with session_maker() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            UPDATE calls
                            SET state = :failed,
                                failure_reason = :reason,
                                version = version + 1,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :call_id
                            """
                        ),
                        {
                            "failed": CallState.FAILED,
                            "reason": "PROVIDER_REJECT",
                            "call_id": call_id,
                        },
                    )

                    await release_agent(session, agent_id)
                    await release_borrower(
                        session,
                        borrower_id,
                        BorrowerState.PENDING,
                    )

    return initiated