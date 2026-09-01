import asyncio

import uvicorn

from smartdialer.api.app import app, app_registry
from smartdialer.config import settings
from smartdialer.db import async_session_maker, init_db
from smartdialer.workers.dialer_worker import DialerWorker


async def main() -> None:
    # 1. Initialize the database schema (creates tables if they don't exist)
    await init_db()

    # 2. Create the dialer worker that runs the pacing loop
    worker = DialerWorker(
        session_maker=async_session_maker,
        provider_registry=app_registry,
    )

    # 3. Configure Uvicorn to run the FastAPI app
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)

    # 4. Run the web server and the background dialer worker concurrently
    await asyncio.gather(
        server.serve(),
        worker.run(settings.pacing_interval_sec),
    )


if __name__ == "__main__":
    asyncio.run(main())