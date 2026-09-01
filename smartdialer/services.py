import json
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy import text

from smartdialer.allocator.call_allocator import (
    release_agent,
    release_borrower,
    reserve_available_agent,
    set_agent_state,
)
from smartdialer.engine.context import DialerContext
from smartdialer.models import Campaign
from smartdialer.states import (
    ACTIVE_CALL_STATES,
    CONNECTED_CALL_STATES,
    VALID_CALL_TRANSITIONS,
    AgentState,
    BorrowerState,
    CallState,
)


async def get_dialer_context(
    session,
    campaign_id: str,
    provider_registry=None,
) -> Optional[DialerContext]:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        return None

    available_agents = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM agents
            WHERE campaign_id = :campaign_id
              AND state = :available
            """
        ),
        {
            "campaign_id": campaign_id,
            "available": AgentState.AVAILABLE,
        },
    )

    active_calls = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM calls
            WHERE campaign_id = :campaign_id
              AND state = ANY(:active_states)
            """
        ),
        {
            "campaign_id": campaign_id,
            "active_states": ACTIVE_CALL_STATES,
        },
    )

    active_agent_calls = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM calls
            WHERE campaign_id = :campaign_id
              AND agent_id IS NOT NULL
              AND state = ANY(:active_states)
            """
        ),
        {
            "campaign_id": campaign_id,
            "active_states": ACTIVE_CALL_STATES,
        },
    )

    active_connections = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM calls
            WHERE campaign_id = :campaign_id
              AND state = ANY(:connected_states)
            """
        ),
        {
            "campaign_id": campaign_id,
            "connected_states": CONNECTED_CALL_STATES,
        },
    )

    ringing_calls = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM calls
            WHERE campaign_id = :campaign_id
              AND state = :ringing
            """
        ),
        {
            "campaign_id": campaign_id,
            "ringing": CallState.RINGING,
        },
    )

    queued_borrowers = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM borrowers
            WHERE campaign_id = :campaign_id
              AND state = :pending
            """
        ),
        {
            "campaign_id": campaign_id,
            "pending": BorrowerState.PENDING,
        },
    )

    completed_calls = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM calls
            WHERE campaign_id = :campaign_id
              AND state = :completed
            """
        ),
        {
            "campaign_id": campaign_id,
            "completed": CallState.COMPLETED,
        },
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
        {
            "campaign_id": campaign_id,
        },
    )

    recent_abandon_rate = abandoned_calls / max(1, completed_calls + abandoned_calls)

    provider_error_rate = 0.0
    if provider_registry is not None and provider_registry.providers:
        provider = provider_registry.choose_provider()
        provider_error_rate = provider_registry.error_rate(provider.name)

    return DialerContext(
        campaign_id=campaign_id,
        mode=campaign.mode,
        available_agents=int(available_agents or 0),
        active_calls=int(active_calls or 0),
        active_agent_calls=int(active_agent_calls or 0),
        active_connections=int(active_connections or 0),
        ringing_calls=int(ringing_calls or 0),
        queued_borrowers=int(queued_borrowers or 0),
        answer_rate=campaign.answer_rate,
        avg_talk_time_sec=campaign.avg_talk_time_sec,
        avg_wrap_time_sec=campaign.avg_wrap_time_sec,
        overdial_factor=campaign.overdial_factor,
        provider_error_rate=provider_error_rate,
        recent_abandon_rate=recent_abandon_rate,
    )


async def release_wrap_up_agents(session, campaign_id: str) -> None:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        return

    cutoff = datetime.utcnow() - timedelta(seconds=max(0, campaign.avg_wrap_time_sec))

    await session.execute(
        text(
            """
            UPDATE agents
            SET state = :available,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = :campaign_id
              AND state = :wrap_up
              AND updated_at < :cutoff
            """
        ),
        {
            "available": AgentState.AVAILABLE,
            "campaign_id": campaign_id,
            "wrap_up": AgentState.WRAP_UP,
            "cutoff": cutoff,
        },
    )


async def release_stale_calls(
    session,
    campaign_id: str,
    timeout_sec: int = 30,
) -> None:
    """
    Handles worker-crash-like scenarios.

    If a call remains in an active pre-complete state for too long,
    mark it FAILED and release reserved resources.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=timeout_sec)

    rows = (
        await session.execute(
            text(
                """
                SELECT id, agent_id, borrower_id, state
                FROM calls
                WHERE campaign_id = :campaign_id
                  AND state = ANY(:states)
                  AND updated_at < :cutoff
                FOR UPDATE SKIP LOCKED
                LIMIT 100
                """
            ),
            {
                "campaign_id": campaign_id,
                "states": [
                    CallState.RESERVED,
                    CallState.INITIATED,
                    CallState.RINGING,
                    CallState.ANSWERED,
                ],
                "cutoff": cutoff,
            },
        )
    ).fetchall()

    for row in rows:
        call_id = row[0]
        agent_id = row[1]
        borrower_id = row[2]

        await session.execute(
            text(
                """
                UPDATE calls
                SET state = :failed,
                    failure_reason = 'STALE',
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :call_id
                """
            ),
            {
                "failed": CallState.FAILED,
                "call_id": call_id,
            },
        )

        await release_agent(session, agent_id)
        await release_borrower(session, borrower_id, BorrowerState.PENDING)


async def _handle_answered(session, call_row) -> None:
    agent_id = call_row.agent_id

    if not agent_id:
        agent_id = await reserve_available_agent(session, call_row.campaign_id)

        if not agent_id:
            # Borrower answered, but no agent is available.
            # This is an abandoned connected call.
            await session.execute(
                text(
                    """
                    UPDATE calls
                    SET state = :failed,
                        failure_reason = 'ABANDONED',
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :call_id
                      AND state = :answered
                    """
                ),
                {
                    "failed": CallState.FAILED,
                    "call_id": call_row.id,
                    "answered": CallState.ANSWERED,
                },
            )
            await release_borrower(
                session,
                call_row.borrower_id,
                BorrowerState.FAILED,
            )
            return

        await session.execute(
            text(
                """
                UPDATE calls
                SET agent_id = :agent_id,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :call_id
                """
            ),
            {
                "agent_id": agent_id,
                "call_id": call_row.id,
            },
        )

    await set_agent_state(
        session,
        agent_id,
        AgentState.RESERVED,
        [AgentState.AVAILABLE],
    )

    await set_agent_state(
        session,
        agent_id,
        AgentState.CONNECTED,
        [AgentState.RESERVED, AgentState.DIALING],
    )

    await session.execute(
        text(
            """
            UPDATE calls
            SET state = :connected,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :call_id
              AND state = :answered
            """
        ),
        {
            "connected": CallState.CONNECTED,
            "call_id": call_row.id,
            "answered": CallState.ANSWERED,
        },
    )

    await session.execute(
        text(
            """
            UPDATE borrowers
            SET state = :called,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :borrower_id
            """
        ),
        {
            "called": BorrowerState.CALLED,
            "borrower_id": call_row.borrower_id,
        },
    )


async def _handle_connected(session, call_row) -> None:
    agent_id = call_row.agent_id

    if not agent_id:
        agent_id = await reserve_available_agent(session, call_row.campaign_id)

        if not agent_id:
            await session.execute(
                text(
                    """
                    UPDATE calls
                    SET state = :failed,
                        failure_reason = 'ABANDONED',
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :call_id
                      AND state = :connected
                    """
                ),
                {
                    "failed": CallState.FAILED,
                    "call_id": call_row.id,
                    "connected": CallState.CONNECTED,
                },
            )
            await release_borrower(
                session,
                call_row.borrower_id,
                BorrowerState.FAILED,
            )
            return

        await session.execute(
            text(
                """
                UPDATE calls
                SET agent_id = :agent_id,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :call_id
                """
            ),
            {
                "agent_id": agent_id,
                "call_id": call_row.id,
            },
        )

    await set_agent_state(
        session,
        agent_id,
        AgentState.CONNECTED,
        [AgentState.AVAILABLE, AgentState.RESERVED, AgentState.DIALING],
    )

    await session.execute(
        text(
            """
            UPDATE borrowers
            SET state = :called,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :borrower_id
            """
        ),
        {
            "called": BorrowerState.CALLED,
            "borrower_id": call_row.borrower_id,
        },
    )


async def _handle_completed(session, call_row) -> None:
    if call_row.agent_id:
        await set_agent_state(
            session,
            call_row.agent_id,
            AgentState.WRAP_UP,
            [
                AgentState.CONNECTED,
                AgentState.DIALING,
                AgentState.RESERVED,
            ],
        )

    await release_borrower(
        session,
        call_row.borrower_id,
        BorrowerState.COMPLETED,
    )


async def _handle_failed(session, call_row, reason: str) -> None:
    if call_row.agent_id:
        await release_agent(session, call_row.agent_id)

    borrower_state = BorrowerState.PENDING

    if call_row.state in {CallState.ANSWERED, CallState.CONNECTED}:
        borrower_state = BorrowerState.FAILED

    await release_borrower(session, call_row.borrower_id, borrower_state)


async def process_event(
    session_maker,
    payload: dict,
    provider_registry=None,
) -> dict:
    event_id = payload.get("event_id") or str(uuid4())
    call_id = payload.get("call_id")
    event_type = str(payload.get("event_type", "")).upper()

    if not call_id or not event_type:
        return {"status": "bad_request"}

    async with session_maker() as session:
        async with session.begin():
            existing_event = await session.scalar(
                text(
                    """
                    SELECT event_id
                    FROM provider_events
                    WHERE event_id = :event_id
                    """
                ),
                {"event_id": event_id},
            )

            if existing_event:
                return {"status": "duplicate"}

            call_row = (
                await session.execute(
                    text(
                        """
                        SELECT id, state, campaign_id, agent_id, borrower_id, provider
                        FROM calls
                        WHERE id = :call_id
                        FOR UPDATE
                        """
                    ),
                    {"call_id": call_id},
                )
            ).first()

            if call_row is None:
                return {"status": "not_found"}

            current_state = call_row.state

            if current_state not in VALID_CALL_TRANSITIONS.get(event_type, set()):
                return {
                    "status": "invalid_transition",
                    "current_state": current_state,
                    "received_event": event_type,
                }

            inserted = await session.execute(
                text(
                    """
                    INSERT INTO provider_events (
                        event_id,
                        call_id,
                        event_type,
                        raw,
                        created_at
                    )
                    VALUES (
                        :event_id,
                        :call_id,
                        :event_type,
                        :raw,
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (event_id) DO NOTHING
                    RETURNING event_id
                    """
                ),
                {
                    "event_id": event_id,
                    "call_id": call_id,
                    "event_type": event_type,
                    "raw": json.dumps(payload, default=str),
                },
            )

            if inserted.first() is None:
                return {"status": "duplicate"}

            await session.execute(
                text(
                    """
                    UPDATE calls
                    SET state = :state,
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :call_id
                    """
                ),
                {
                    "state": event_type,
                    "call_id": call_id,
                },
            )

            if event_type == CallState.ANSWERED:
                await _handle_answered(session, call_row)
            elif event_type == CallState.CONNECTED:
                await _handle_connected(session, call_row)
            elif event_type == CallState.COMPLETED:
                await _handle_completed(session, call_row)
            elif event_type == CallState.FAILED:
                await _handle_failed(session, call_row, "PROVIDER_FAILED")

            if provider_registry is not None:
                if event_type == CallState.COMPLETED:
                    provider_registry.record_success(call_row.provider)
                elif event_type == CallState.FAILED:
                    provider_registry.record_failure(call_row.provider)

            return {
                "status": "ok",
                "call_id": call_id,
                "event_type": event_type,
            }