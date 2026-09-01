from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from smartdialer.services import process_event

router = APIRouter()


class ProviderEventPayload(BaseModel):
    event_id: str
    call_id: str
    event_type: str
    provider: Optional[str] = None
    provider_call_id: Optional[str] = None


@router.post("/webhooks/provider-event")
async def provider_event(payload: ProviderEventPayload, request: Request):
    session_maker = request.app.state.session_maker
    registry = getattr(request.app.state, "registry", None)

    return await process_event(
        session_maker,
        payload.model_dump(),
        registry,
    )