from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from smartdialer.config import settings

async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    from smartdialer import models  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def reset_db() -> None:
    from smartdialer import models  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)