from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from smartdialer.states import AgentState, BorrowerState, CallState


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(120), default="Campaign")
    mode: Mapped[str] = mapped_column(String(20), default="progressive")
    answer_rate: Mapped[float] = mapped_column(Float, default=0.30)
    avg_talk_time_sec: Mapped[int] = mapped_column(Integer, default=120)
    avg_wrap_time_sec: Mapped[int] = mapped_column(Integer, default=10)
    overdial_factor: Mapped[float] = mapped_column(Float, default=1.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id"),
        index=True,
    )
    state: Mapped[str] = mapped_column(String(20), default=AgentState.OFFLINE)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Borrower(Base):
    __tablename__ = "borrowers"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id"),
        index=True,
    )
    phone: Mapped[str] = mapped_column(String(32), default="+10000000000")
    state: Mapped[str] = mapped_column(String(20), default=BorrowerState.PENDING)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id"),
        index=True,
    )
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("agents.id"),
        nullable=True,
        index=True,
    )
    borrower_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("borrowers.id"),
        nullable=True,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(20), default=CallState.QUEUED)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ProviderEvent(Base):
    __tablename__ = "provider_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)