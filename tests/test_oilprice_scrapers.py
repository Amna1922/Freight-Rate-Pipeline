from datetime import datetime, timezone

import httpx
import pytest

from app.db import settings
from app.scrapers.scfi import fetch_scfi_rates
from app.scrapers.wci import fetch_wci_rates


@pytest.mark.asyncio
async def test_wci_and_scfi_use_oilprice_api(monkeypatch):
    monkeypatch.setattr(settings, "oilprice_api_key", "test-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        code = request.url.params["by_code"]
        price = "2450.00" if code == "DREWRY_WCI_USD" else "1800.00"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "price": price,
                    "currency": "USD",
                    "code": code,
                    "created_at": "2026-09-18T08:00:00.000Z",
                    "type": "spot",
                },
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        wci_rates = await fetch_wci_rates(client, [("CNSHA", "USLAX")])
        scfi_rates = await fetch_scfi_rates(client, [("CNSHA", "USLAX")])

    assert wci_rates[0].rate == 2450
    assert wci_rates[0].source_id == "SRC-WCI-001"
    assert scfi_rates[0].rate == 1800
    assert scfi_rates[0].source_id == "SRC-SCFI-001"
