import asyncio
import random
from typing import Optional
from uuid import uuid4

from smartdialer.providers.base import ProviderResponse, TelecomProvider


class ProviderA(TelecomProvider):
    """
    Fast, mostly reliable provider.
    """

    name = "provider_a"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        event_callback=None,
        answer_rate: float = 0.5,
        talk_time_sec: float = 0.2,
        failure_rate: float = 0.02,
        latency_sec: float = 0.02,
    ):
        super().__init__(webhook_url=webhook_url, event_callback=event_callback)
        self.answer_rate = answer_rate
        self.talk_time_sec = talk_time_sec
        self.failure_rate = failure_rate
        self.latency_sec = latency_sec

    async def initiate_call(
        self,
        call_id: str,
        to_number: str,
        from_number: str = "1000",
    ) -> ProviderResponse:
        provider_call_id = str(uuid4())

        await asyncio.sleep(self.latency_sec)

        if random.random() < self.failure_rate:
            return ProviderResponse(
                accepted=False,
                provider_call_id=provider_call_id,
                error="provider_reject",
            )

        asyncio.create_task(self._simulate_call(call_id, provider_call_id))

        return ProviderResponse(
            accepted=True,
            provider_call_id=provider_call_id,
        )

    async def _simulate_call(self, call_id: str, provider_call_id: str) -> None:
        await asyncio.sleep(0.08)
        await self.emit_event(call_id, "RINGING", provider_call_id)

        if random.random() < self.answer_rate:
            await asyncio.sleep(0.08)
            await self.emit_event(call_id, "ANSWERED", provider_call_id)

            await asyncio.sleep(max(0.02, self.talk_time_sec))
            await self.emit_event(call_id, "COMPLETED", provider_call_id)
        else:
            await asyncio.sleep(0.10)
            await self.emit_event(call_id, "FAILED", provider_call_id)

    async def hangup(self, provider_call_id: str) -> bool:
        return True