import asyncio
import random
from typing import Optional
from uuid import uuid4

from smartdialer.providers.base import ProviderResponse, TelecomProvider


class ProviderB(TelecomProvider):
    """
    Slower provider with timeouts, duplicates, and occasional out-of-order events.
    """

    name = "provider_b"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        event_callback=None,
        answer_rate: float = 0.4,
        talk_time_sec: float = 0.3,
        timeout_rate: float = 0.15,
        latency_min_sec: float = 0.03,
        latency_max_sec: float = 0.10,
    ):
        super().__init__(webhook_url=webhook_url, event_callback=event_callback)
        self.answer_rate = answer_rate
        self.talk_time_sec = talk_time_sec
        self.timeout_rate = timeout_rate
        self.latency_min_sec = latency_min_sec
        self.latency_max_sec = latency_max_sec

    async def initiate_call(
        self,
        call_id: str,
        to_number: str,
        from_number: str = "1000",
    ) -> ProviderResponse:
        provider_call_id = str(uuid4())

        await asyncio.sleep(random.uniform(self.latency_min_sec, self.latency_max_sec))

        if random.random() < self.timeout_rate:
            return ProviderResponse(
                accepted=False,
                provider_call_id=provider_call_id,
                error="timeout",
            )

        asyncio.create_task(self._simulate_call(call_id, provider_call_id))

        return ProviderResponse(
            accepted=True,
            provider_call_id=provider_call_id,
        )

    async def _simulate_call(self, call_id: str, provider_call_id: str) -> None:
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await self.emit_event(call_id, "RINGING", provider_call_id)

        if random.random() >= self.answer_rate:
            await asyncio.sleep(random.uniform(0.05, 0.20))
            await self.emit_event(call_id, "FAILED", provider_call_id)
            return

        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Occasionally send COMPLETED before ANSWERED to simulate out-of-order events.
        if random.random() < 0.10:
            await self.emit_event(call_id, "COMPLETED", provider_call_id)
            await self.emit_event(call_id, "ANSWERED", provider_call_id)
            return

        await self.emit_event(call_id, "ANSWERED", provider_call_id)

        # Duplicate ANSWERED event.
        if random.random() < 0.25:
            await self.emit_event(call_id, "ANSWERED", provider_call_id)

        await asyncio.sleep(max(0.02, self.talk_time_sec))
        await self.emit_event(call_id, "COMPLETED", provider_call_id)

        # Duplicate COMPLETED event.
        if random.random() < 0.15:
            await self.emit_event(call_id, "COMPLETED", provider_call_id)

    async def hangup(self, provider_call_id: str) -> bool:
        return True