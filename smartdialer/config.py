import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://smartdialer:password@localhost:5432/smartdialer",
    )
    webhook_base_url: str = os.getenv(
        "WEBHOOK_BASE_URL",
        "http://localhost:8000",
    )
    pacing_interval_sec: float = float(os.getenv("PACING_INTERVAL_SEC", "2.0"))


settings = Settings()