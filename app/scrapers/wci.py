import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import re
import httpx
from bs4 import BeautifulSoup
from ..db import settings
from ..models import RawRate
from . import ScraperError

SOURCE_ID, PUBLISHER = "SRC-WCI-001", "Drewry World Container Index"
BASE_URL = settings.wci_base_url


async def fetch_wci_rates(client: httpx.AsyncClient, lanes: list[tuple[str, str]]) -> list[RawRate]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.get(BASE_URL, headers={"User-Agent": "FreightRatePipeline/1.0 (+contact@example.com)"})
            if response.status_code >= 500:
                raise httpx.HTTPStatusError("upstream server error", request=response.request, response=response)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            values = re.findall(r"(?:USD|\$)\s*([\d,]+(?:\.\d+)?)", text)
            if not values:
                raise ValueError("World Container Index rate not found")
            result = []
            for origin, destination in lanes:
                result.append(RawRate(source_id=SOURCE_ID, publisher=PUBLISHER, origin=origin,
                    destination=destination, mode="ocean", container="40HC",
                    rate=Decimal(values[0].replace(",", "")), retrieved_at=datetime.now(timezone.utc),
                    source_url=str(response.url)))
            return result
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
            last = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
    raise ScraperError(SOURCE_ID, str(last))
