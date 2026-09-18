from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ..db import settings
from ..models import RateQuote


class BaseScraper(ABC):
    name: str

    @abstractmethod
    async def fetch(self, origin: str, destination: str, equipment: str) -> RateQuote | None:
        raise NotImplementedError

    async def request(self, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", settings.scraper_user_agent)
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds,
                                     follow_redirects=True) as client:
            return await client.get(url, headers=headers, **kwargs)


class ScraperRegistry:
    def __init__(self, scrapers: list[BaseScraper] | None = None):
        from .fbx import FBXScraper
        from .wci import WCIScraper
        self.scrapers = scrapers if scrapers is not None else [FBXScraper(), WCIScraper()]

    async def scrape_all(self, origin: str, destination: str, equipment: str) -> list[RateQuote]:
        import asyncio
        results = await asyncio.gather(
            *(scraper.fetch(origin, destination, equipment) for scraper in self.scrapers),
            return_exceptions=True,
        )
        return [item for item in results if isinstance(item, RateQuote)]
