from datetime import datetime, timezone
from decimal import Decimal

from .base import BaseScraper
from ..models import RateQuote


class DemoScraper(BaseScraper):
    """Safe local adapter used for development; replace with licensed sources in production."""
    name = "demo"

    async def fetch(self, origin: str, destination: str, equipment: str) -> RateQuote:
        return RateQuote(source=self.name, origin=origin, destination=destination,
                         equipment=equipment, amount=Decimal("1250.00"), currency="USD",
                         quoted_at=datetime.now(timezone.utc), metadata_json={"demo": True})
