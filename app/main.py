import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .consensus import ConsensusError, compute_consensus
from .db import (
    ConsensusFreightRates,
    get_cached_consensus,
    get_session,
    init_models,
    insert_raw_rates,
    SessionLocal,
    settings,
    upsert_consensus,
    write_audit,
)
from .models import (
    ApiMeta,
    ErrorResponse,
    FreightRateData,
    FreightRateRequest,
    FreightRateResponse,
    Freshness,
    License,
    Meta,
    Provenance,
    RateLimit,
    Trust,
)
from .scrapers import ScraperError, fetch_scfi_rates, fetch_wci_rates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEFAULT_LANES = [("CNSHA", "USLAX")]
SOURCE_IDS = ("SRC-WCI-001", "SRC-SCFI-001")
CACHE_LOCK = asyncio.Lock()


def _error_response(request_id: str, reason: str, failed: list[str]) -> JSONResponse:
    error = ErrorResponse(
        error="upstream_unavailable",
        error_code="UPSTREAM_UNAVAILABLE",
        details={
            "sources_tried": list(SOURCE_IDS),
            "sources_failed": failed,
            "reason": reason,
        },
        request_id=request_id,
        served_at=datetime.now(timezone.utc),
    )
    return JSONResponse(status_code=503, content=error.model_dump(mode="json"))


def _freshness(timestamp: datetime, now: datetime) -> Freshness:
    age = max(0, int((now - timestamp).total_seconds()))
    return Freshness(
        age_seconds=age,
        ttl_seconds=settings.ttl_seconds,
        stale=age >= settings.ttl_seconds,
    )


def _response_from_cache(
    row: ConsensusFreightRates,
    request_id: str,
    latency_ms: int,
    now: datetime,
) -> FreightRateResponse:
    provenance = [
        Provenance.model_validate(item)
        for item in (row.provenance or [])
    ]
    source_timestamp = min(
        (item.retrieved_at for item in provenance),
        default=row.served_at,
    )
    return FreightRateResponse(
        data=FreightRateData(
            origin=row.origin,
            destination=row.destination,
            mode=row.mode,
            container=row.container,
            median_rate=row.median_rate,
            currency=row.currency,
            valid_for=row.valid_for,
            sample_size=row.sample_size,
            p25_rate=row.p25_rate,
            p75_rate=row.p75_rate,
        ),
        meta=Meta(
            request_id=request_id,
            served_at=now,
            source_last_updated_at=source_timestamp,
            freshness=_freshness(source_timestamp, now),
            provenance=provenance,
            trust=Trust(
                confidence=float(row.confidence),
                quality_score=float(row.quality_score),
                verified=row.sample_size >= 2,
            ),
            license=License(type="commercial", usage="agent_runtime"),
            api=ApiMeta(
                latency_ms=latency_ms,
                rate_limit=RateLimit(limit=100, window_seconds=60),
                cache_hit=True,
            ),
            warnings=list(row.warnings or []),
        ),
    )


async def _fetch_source_rates(
    lanes: list[tuple[str, str]],
) -> tuple[list, list[str], list[str]]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        results = await asyncio.gather(
            fetch_wci_rates(client, lanes),
            fetch_scfi_rates(client, lanes),
            return_exceptions=True,
        )

    rates = []
    warnings: list[str] = []
    failed_sources: list[str] = []
    for source_id, result in zip(SOURCE_IDS, results):
        if isinstance(result, ScraperError):
            warnings.append(f"source_down: {result.source_id}")
            failed_sources.append(result.source_id)
        elif isinstance(result, Exception):
            logger.error("%s scraper failed: %s", source_id, result)
            warnings.append(f"source_down: {source_id}")
            failed_sources.append(source_id)
        else:
            rates.extend(result)
            if not result:
                failed_sources.append(source_id)
                warnings.append(f"source_down: {source_id}")
    return rates, warnings, failed_sources


async def _ingestion_loop() -> None:
    while True:
        try:
            await asyncio.sleep(settings.scrape_interval_minutes * 60)
            rates, warnings, _ = await _fetch_source_rates(DEFAULT_LANES)
            if not rates:
                logger.warning("background ingestion returned no rates: %s", warnings)
                continue
            consensus = compute_consensus(rates)
            now = datetime.now(timezone.utc)
            async with SessionLocal() as session:
                await insert_raw_rates(
                    session,
                    [
                        {
                            "source_id": rate.source_id,
                            "publisher": rate.publisher,
                            "origin": rate.origin,
                            "destination": rate.destination,
                            "mode": rate.mode,
                            "container": rate.container,
                            "rate": rate.rate,
                            "currency": rate.currency,
                            "retrieved_at": rate.retrieved_at,
                            "source_url": rate.source_url,
                            "payload": rate.model_dump(mode="json"),
                        }
                        for rate in rates
                    ],
                )
                await upsert_consensus(
                    session,
                    {
                        "origin": DEFAULT_LANES[0][0],
                        "destination": DEFAULT_LANES[0][1],
                        "mode": "ocean",
                        "container": "40HC",
                        "median_rate": consensus.median_rate,
                        "p25_rate": consensus.p25_rate,
                        "p75_rate": consensus.p75_rate,
                        "currency": rates[0].currency,
                        "sample_size": consensus.sample_size,
                        "confidence": Decimal(str(consensus.confidence)),
                        "quality_score": Decimal(str(consensus.quality_score)),
                        "valid_for": date.today(),
                        "served_at": now,
                        "provenance": [item.model_dump(mode="json") for item in consensus.provenance],
                        "warnings": warnings + consensus.warnings,
                    },
                )
                await session.commit()
            logger.info("background ingestion stored %d rates", len(rates))
        except asyncio.CancelledError:
            raise
        except (ScraperError, ConsensusError, SQLAlchemyError, httpx.HTTPError) as exc:
            logger.error("background ingestion failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    task = asyncio.create_task(_ingestion_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Freight Rate Pipeline", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "up"}
    except SQLAlchemyError as exc:
        logger.error("health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.get(
    "/v1/logistics/freight/rate",
    response_model=FreightRateResponse,
    responses={503: {"model": ErrorResponse}},
)
async def freight_rate(
    origin: str = Query(...),
    destination: str = Query(...),
    mode: str = Query("ocean"),
    container: str = Query("40HC"),
    session: AsyncSession = Depends(get_session),
) -> FreightRateResponse | JSONResponse:
    started = time.perf_counter()
    request_id = "req_" + uuid4().hex
    request = FreightRateRequest(
        origin=origin,
        destination=destination,
        mode=mode,
        container=container,
    )
    now = datetime.now(timezone.utc)
    cached = await get_cached_consensus(
        session,
        request.origin,
        request.destination,
        request.mode,
        request.container,
    )
    if cached and (now - cached.served_at).total_seconds() < settings.cache_ttl_seconds:
        return _response_from_cache(
            cached,
            request_id,
            int((time.perf_counter() - started) * 1000),
            now,
        )

    async with CACHE_LOCK:
        cached = await get_cached_consensus(
            session,
            request.origin,
            request.destination,
            request.mode,
            request.container,
        )
        now = datetime.now(timezone.utc)
        if cached and (now - cached.served_at).total_seconds() < settings.cache_ttl_seconds:
            return _response_from_cache(
                cached,
                request_id,
                int((time.perf_counter() - started) * 1000),
                now,
            )
        rates, warnings, failed_sources = await _fetch_source_rates(
            [(request.origin, request.destination)]
        )
    if not rates:
        return _error_response(
            request_id,
            "both sources failed or returned no data",
            failed_sources,
        )
    try:
        consensus = compute_consensus(rates)
    except ConsensusError:
        return _error_response(
            request_id,
            "fewer than 2 valid rates after outlier rejection",
            failed_sources,
        )

    now = datetime.now(timezone.utc)
    oldest = min(rate.retrieved_at for rate in rates)
    latency = int((time.perf_counter() - started) * 1000)
    response = FreightRateResponse(
        data=FreightRateData(
            origin=request.origin,
            destination=request.destination,
            mode=request.mode,
            container=request.container,
            median_rate=consensus.median_rate,
            currency=rates[0].currency,
            valid_for=date.today(),
            sample_size=consensus.sample_size,
            p25_rate=consensus.p25_rate,
            p75_rate=consensus.p75_rate,
        ),
        meta=Meta(
            request_id=request_id,
            served_at=now,
            source_last_updated_at=oldest,
            freshness=_freshness(oldest, now),
            provenance=consensus.provenance,
            trust=Trust(
                confidence=consensus.confidence,
                quality_score=consensus.quality_score,
                verified=len(rates) >= 2,
            ),
            license=License(type="commercial", usage="agent_runtime"),
            api=ApiMeta(
                latency_ms=latency,
                rate_limit=RateLimit(limit=100, window_seconds=60),
                cache_hit=False,
            ),
            warnings=warnings + consensus.warnings,
        ),
    )
    await insert_raw_rates(
        session,
        [
            {
                "source_id": rate.source_id,
                "publisher": rate.publisher,
                "origin": rate.origin,
                "destination": rate.destination,
                "mode": rate.mode,
                "container": rate.container,
                "rate": rate.rate,
                "currency": rate.currency,
                "retrieved_at": rate.retrieved_at,
                "source_url": rate.source_url,
                "payload": rate.model_dump(mode="json"),
            }
            for rate in rates
        ],
    )
    await upsert_consensus(
        session,
        {
            "origin": request.origin,
            "destination": request.destination,
            "mode": request.mode,
            "container": request.container,
            "median_rate": consensus.median_rate,
            "p25_rate": consensus.p25_rate,
            "p75_rate": consensus.p75_rate,
            "currency": rates[0].currency,
            "sample_size": consensus.sample_size,
            "confidence": Decimal(str(consensus.confidence)),
            "quality_score": Decimal(str(consensus.quality_score)),
            "valid_for": date.today(),
            "served_at": now,
            "provenance": [item.model_dump(mode="json") for item in consensus.provenance],
            "warnings": warnings + consensus.warnings,
        },
    )
    await write_audit(
        session,
        {
            "request_id": request_id,
            "endpoint": "/v1/logistics/freight/rate",
            "query_params": request.model_dump(),
            "response_status": 200,
            "latency_ms": latency,
            "warnings": response.meta.warnings,
        },
    )
    await session.commit()
    return response
