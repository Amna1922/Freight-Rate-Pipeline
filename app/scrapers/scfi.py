import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ..db import settings
from ..models import RawRate
from . import ScraperError

SOURCE_ID = "SRC-SCFI-001"
PUBLISHER = "Shanghai Containerized Freight Index"
INDEX_CODE = "SCFI_INDEX"
USER_AGENT = "FreightRatePipeline/1.0 (+contact@example.com)"


def _retrieved_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def fetch_scfi_rates(client: httpx.AsyncClient, lanes: list[tuple[str, str]]) -> list[RawRate]:
    if not settings.oilprice_api_key:
        raise ScraperError(SOURCE_ID, "OILPRICE_API_KEY is not configured")
    last_error: Exception | None = None
    headers = {"Authorization": f"Token {settings.oilprice_api_key}", "User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            response = await client.get(settings.oilprice_api_url, params={"by_code": INDEX_CODE}, headers=headers)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError("OilPriceAPI server error", request=response.request, response=response)
            if response.status_code >= 400:
                raise ScraperError(SOURCE_ID, f"OilPriceAPI returned HTTP {response.status_code}", response.status_code)
            payload = response.json()
            data = payload.get("data", {})
            if payload.get("status") != "success" or data.get("price") is None:
                raise ValueError("OilPriceAPI response did not contain a successful SCFI price")
            rate = Decimal(str(data["price"]))
            if rate <= 0:
                raise ValueError("OilPriceAPI returned a non-positive SCFI price")
            retrieved_at = _retrieved_at(data.get("created_at"))
            return [RawRate(source_id=SOURCE_ID, publisher=PUBLISHER, origin=origin, destination=destination,
                mode="ocean", container="40HC", rate=rate, currency=data.get("currency", "USD"),
                retrieved_at=retrieved_at, source_url=f"{settings.oilprice_api_url}?by_code={INDEX_CODE}")
                for origin, destination in lanes]
        except ScraperError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2**attempt)
    raise ScraperError(SOURCE_ID, str(last_error))
