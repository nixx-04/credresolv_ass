import pytest_asyncio

from smartdialer.db import async_engine, async_session_maker, reset_db


@pytest_asyncio.fixture
async def session():
    # Close connections that were created on a previous test's event loop.
    await async_engine.dispose()

    await reset_db()

    async with async_session_maker() as session:
        yield session

    # Make sure the next test starts with a clean pool on its own loop.
    await async_engine.dispose()