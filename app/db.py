from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://freight:freight@localhost:5432/freight"
    fbx_base_url: str = "https://fbxtotal.com"
    wci_base_url: str = "https://www.drewry.co.uk"
    oilprice_api_key: str = ""
    oilprice_api_url: str = "https://api.oilpriceapi.com/v1/prices/latest"
    ttl_seconds: int = 604800
    scrape_interval_minutes: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Json = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class RawFreightData(Base):
    __tablename__ = "raw_freight_data"
    __table_args__ = (Index("ix_raw_lane_time", "origin", "destination", "mode", "container", "retrieved_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    publisher: Mapped[str] = mapped_column(String(255))
    origin: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    container: Mapped[str] = mapped_column(String(16))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsensusFreightRates(Base):
    __tablename__ = "consensus_freight_rates"
    __table_args__ = (UniqueConstraint("origin", "destination", "mode", "container", "valid_for"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origin: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    container: Mapped[str] = mapped_column(String(16), index=True)
    median_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    p25_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    p75_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    sample_size: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    quality_score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    valid_for: Mapped[datetime] = mapped_column(Date, index=True)
    served_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provenance: Mapped[list] = mapped_column(Json, default=list)
    warnings: Mapped[list] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    query_params: Mapped[dict] = mapped_column(Json, default=dict)
    response_status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def insert_raw_rates(session: AsyncSession, rates: list[dict]) -> int:
    if not rates:
        return 0
    session.add_all([RawFreightData(**rate) for rate in rates])
    await session.flush()
    return len(rates)


async def fetch_recent_raw_rates(session, origin, destination, mode, container, since):
    result = await session.scalars(select(RawFreightData).where(
        RawFreightData.origin == origin, RawFreightData.destination == destination,
        RawFreightData.mode == mode, RawFreightData.container == container,
        RawFreightData.retrieved_at >= since))
    return list(result.all())


async def upsert_consensus(session, consensus: dict) -> None:
    await session.execute(insert(ConsensusFreightRates).values(**consensus).on_conflict_do_update(
        index_elements=["origin", "destination", "mode", "container", "valid_for"], set_=consensus))
    await session.flush()


async def get_cached_consensus(session, origin, destination, mode, container):
    return await session.scalar(select(ConsensusFreightRates).where(
        ConsensusFreightRates.origin == origin, ConsensusFreightRates.destination == destination,
        ConsensusFreightRates.mode == mode, ConsensusFreightRates.container == container
    ).order_by(ConsensusFreightRates.served_at.desc()))


async def write_audit(session: AsyncSession, entry_dict: dict) -> None:
    session.add(AuditLog(**entry_dict))
    await session.flush()


async def init_models() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
