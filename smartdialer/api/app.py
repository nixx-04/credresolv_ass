from contextlib import asynccontextmanager

from fastapi import FastAPI

from smartdialer.api.webhooks import router
from smartdialer.config import settings
from smartdialer.db import async_session_maker, init_db
from smartdialer.providers.provider_a import ProviderA
from smartdialer.providers.provider_b import ProviderB
from smartdialer.providers.registry import ProviderRegistry


def build_default_registry(event_callback=None) -> ProviderRegistry:
    webhook_url = f"{settings.webhook_base_url}/webhooks/provider-event"

    registry = ProviderRegistry()

    registry.add_provider(
        ProviderA(
            webhook_url=None if event_callback else webhook_url,
            event_callback=event_callback,
        )
    )

    registry.add_provider(
        ProviderB(
            webhook_url=None if event_callback else webhook_url,
            event_callback=event_callback,
        )
    )

    return registry


# Providers used by the worker + webhook API when running for real.
app_registry = build_default_registry()


def create_app(
    session_maker=async_session_maker,
    registry: ProviderRegistry = app_registry,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await init_db()
        application.state.session_maker = session_maker
        application.state.registry = registry
        yield

    application = FastAPI(title="SmartDialer", lifespan=lifespan)
    application.include_router(router)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    return application


# The object that `main.py` and uvicorn import.
app = create_app()