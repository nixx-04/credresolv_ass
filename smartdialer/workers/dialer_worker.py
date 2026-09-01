import asyncio

from sqlalchemy import select

from smartdialer.allocator.call_allocator import initiate_approved_calls
from smartdialer.engine.predictive import PredictivePacingEngine
from smartdialer.engine.progressive import ProgressivePacingEngine
from smartdialer.engine.safety_controller import SafetyController
from smartdialer.models import Campaign
from smartdialer.services import (
    get_dialer_context,
    release_stale_calls,
    release_wrap_up_agents,
)


class DialerWorker:
    def __init__(
        self,
        session_maker,
        provider_registry,
        safety_controller: SafetyController | None = None,
    ):
        self.session_maker = session_maker
        self.provider_registry = provider_registry
        self.safety_controller = safety_controller or SafetyController()
        self.progressive_engine = ProgressivePacingEngine()
        self.predictive_engine = PredictivePacingEngine()

    async def run_campaign_tick(self, campaign_id: str) -> dict:
        try:
            async with self.session_maker() as session:
                async with session.begin():
                    await release_wrap_up_agents(session, campaign_id)
                    await release_stale_calls(session, campaign_id)

                    ctx = await get_dialer_context(
                        session,
                        campaign_id,
                        self.provider_registry,
                    )

            if ctx is None:
                return {"status": "campaign_not_found"}

            if ctx.mode == "predictive":
                engine = self.predictive_engine
            else:
                engine = self.progressive_engine

            requested = engine.compute_desired_calls(ctx)
            approved = self.safety_controller.evaluate(requested, ctx)

            initiated = 0

            if approved > 0:
                provider = self.provider_registry.choose_provider()

                initiated = await initiate_approved_calls(
                    self.session_maker,
                    campaign_id,
                    approved,
                    provider,
                    ctx.mode,
                )

            return {
                "campaign_id": campaign_id,
                "mode": ctx.mode,
                "requested": requested,
                "approved": approved,
                "initiated": initiated,
                "available_agents": ctx.available_agents,
                "active_calls": ctx.active_calls,
                "active_connections": ctx.active_connections,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "campaign_id": campaign_id,
                "status": "error",
                "error": str(exc),
            }

    async def run(self, interval_sec: float = 2.0) -> None:
        while True:
            async with self.session_maker() as session:
                result = await session.execute(
                    select(Campaign.id).where(Campaign.active.is_(True))
                )
                campaign_ids = [row[0] for row in result.fetchall()]

            for campaign_id in campaign_ids:
                await self.run_campaign_tick(campaign_id)

            await asyncio.sleep(interval_sec)