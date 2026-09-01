import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx


@dataclass
class ProviderResponse:
    accepted: bool
    provider_call_id: Optional[str] = None
    error: Optional[str] = None


EventCallback = Callable[[dict], Awaitable[None]]


class TelecomProvider(ABC):
    name = "base"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        event_callback: Optional[EventCallback] = None,
    ):
        self.webhook_url = webhook_url
        self.event_callback = event_callback

    @abstractmethod
    async def initiate_call(
        self,
        call_id: str,
        to_number: str,
        from_number: str = "1000",
    ) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> bool:
        raise NotImplementedError

    async def emit_event(
        self,
        call_id: str,
        event_type: str,
        provider_call_id: str,
    ) -> None:
        payload = {
            "event_id": str(uuid.uuid4()),
            "call_id": call_id,
            "provider": self.name,
            "provider_call_id": provider_call_id,
            "event_type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if self.event_callback is not None:
                await self.event_callback(payload)
            elif self.webhook_url:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.post(self.webhook_url, json=payload)
        except Exception:
            # Mock providers should not crash the simulation because webhook delivery failed.
            pass