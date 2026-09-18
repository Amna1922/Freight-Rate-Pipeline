import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import httpx
from bs4 import BeautifulSoup
from ..db import settings
from ..models import RawRate
from . import ScraperError

SOURCE_ID, PUBLISHER = "SRC-FBX-001", "Freightos Baltic Index"
BASE_URL = settings.fbx_base_url


async def fetch_fbx_rates(client: httpx.AsyncClient, lanes: list[tuple[str, str]]) -> list[RawRate]:
    headers = {"User-Agent": "FreightRatePipeline/1.0 (+contact@example.com)"}
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.get(BASE_URL, headers=headers)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError("upstream server error", request=response.request, response=response)
            response.raise_for_status()
            payload = response.json() if "json" in response.headers.get("content-type", "") else None
            text = response.text
            result: list[RawRate] = []
            for origin, destination in lanes:
                value = None
                if isinstance(payload, dict):
                    value = payload.get(f"{origin}-{destination}") or payload.get("rate")
                if value is None:
                    match = BeautifulSoup(text, "html.parser").find(string=lambda s: s and origin in s and destination in s)
                    if match:
                        import re
                        found = re.search(r"[\d,]+(?:\.\d+)?", match.parent.get_text(" "))
                        value = found.group(0) if found else None
                if value is not None:
                    result.append(RawRate(source_id=SOURCE_ID, publisher=PUBLISHER, origin=origin,
                        destination=destination, mode="ocean", container="40HC",
                        rate=Decimal(str(value).replace(",", "")), retrieved_at=datetime.now(timezone.utc),
                        source_url=str(response.url)))
            if not result:
                raise ValueError("no FBX rates matched requested lanes")
            return result
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
            last = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
    raise ScraperError(SOURCE_ID, str(last))
