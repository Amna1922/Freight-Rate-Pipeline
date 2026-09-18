import asyncio
import logging
import time
from datetime import date, datetime, timezone
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .consensus import ConsensusError, compute_consensus
from .db import get_session, init_models, settings, write_audit
from .models import ErrorResponse, FreightRateRequest, FreightRateResponse, FreightRateData, Meta, Freshness, Trust, License, ApiMeta, RateLimit
from .scrapers import ScraperError, fetch_fbx_rates, fetch_wci_rates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Freight Rate Pipeline", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup() -> None:
    await init_models()


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "up"}
    except SQLAlchemyError as exc:
        logger.error("health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.get("/v1/logistics/freight/rate", response_model=FreightRateResponse,
         responses={503: {"model": ErrorResponse}})
async def freight_rate(
    origin: str = Query(...), destination: str = Query(...),
    mode: str = Query("ocean"), container: str = Query("40HC"),
    session: AsyncSession = Depends(get_session),
) -> FreightRateResponse:
    started = time.perf_counter()
    request_id = "req_" + uuid4().hex
    request = FreightRateRequest(origin=origin, destination=destination, mode=mode, container=container)
    warnings: list[str] = []
    lanes = [(request.origin, request.destination)]
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        results = await asyncio.gather(fetch_fbx_rates(client, lanes), fetch_wci_rates(client, lanes), return_exceptions=True)
    rates = []
    for result in results:
        if isinstance(result, ScraperError):
            warnings.append(f"source_down: {result.source_id}")
        elif isinstance(result, Exception):
            warnings.append("source_down: unknown")
        else:
            rates.extend(result)
    failed_sources = [
        source_id
        for source_id, result in zip(("SRC-FBX-001", "SRC-WCI-001"), results)
        if isinstance(result, Exception) or not result
    ]
    if not rates:
        error = ErrorResponse(error="upstream sources unavailable", error_code="UPSTREAM_UNAVAILABLE",
                              details={"sources_tried": ["SRC-FBX-001", "SRC-WCI-001"],
                                       "sources_failed": failed_sources,
                                       "reason": "both sources failed or returned no data"},
                              request_id=request_id, served_at=datetime.now(timezone.utc))
        return JSONResponse(status_code=503, content=error.model_dump(mode="json"))
    try:
        consensus = compute_consensus(rates)
    except ConsensusError:
        error = ErrorResponse(
            error="upstream_unavailable",
            error_code="UPSTREAM_UNAVAILABLE",
            details={"sources_tried": ["SRC-FBX-001", "SRC-WCI-001"],
                     "sources_failed": failed_sources,
                     "reason": "fewer than 2 valid rates after outlier rejection"},
            request_id=request_id,
            served_at=datetime.now(timezone.utc),
        )
        return JSONResponse(status_code=503, content=error.model_dump(mode="json"))
    now = datetime.now(timezone.utc)
    latest = max(rate.retrieved_at for rate in rates)
    age = max(0, int((now - latest).total_seconds()))
    latency = int((time.perf_counter() - started) * 1000)
    response = FreightRateResponse(
        data=FreightRateData(origin=request.origin, destination=request.destination, mode=request.mode,
            container=request.container, median_rate=consensus.median_rate, currency=rates[0].currency,
            valid_for=date.today(), sample_size=consensus.sample_size, p25_rate=consensus.p25_rate, p75_rate=consensus.p75_rate),
        meta=Meta(request_id=request_id, served_at=now, source_last_updated_at=latest,
            freshness=Freshness(age_seconds=age, ttl_seconds=settings.ttl_seconds, stale=age >= settings.ttl_seconds),
            provenance=consensus.provenance, trust=Trust(confidence=consensus.confidence,
                quality_score=consensus.quality_score, verified=len(rates) >= 2),
            license=License(type="commercial", usage="agent_runtime"),
            api=ApiMeta(latency_ms=latency, rate_limit=RateLimit(limit=100, window_seconds=60)),
            warnings=warnings + consensus.warnings))
    await write_audit(session, {"request_id": request_id, "endpoint": "/v1/logistics/freight/rate",
        "query_params": request.model_dump(), "response_status": 200, "latency_ms": latency, "warnings": response.meta.warnings})
    await session.commit()
    return response
