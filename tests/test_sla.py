import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app import main
from app.db import get_session
from app.models import RawRate


@pytest.fixture
def api_client(monkeypatch):
    class FakeSession:
        async def commit(self):
            return None

    async def override_session():
        yield FakeSession()

    main.app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main, "insert_raw_rates", _noop)
    monkeypatch.setattr(main, "upsert_consensus", _noop)
    monkeypatch.setattr(main, "write_audit", _noop)
    yield
    main.app.dependency_overrides.clear()


async def _noop(*args, **kwargs):
    return None


def _rates():
    now = datetime.now(timezone.utc)
    return [
        RawRate(
            source_id="SRC-WCI-001",
            publisher="Drewry World Container Index",
            origin="CNSHA",
            destination="USLAX",
            mode="ocean",
            container="40HC",
            rate=Decimal("2450"),
            retrieved_at=now,
            source_url="https://example.test/wci",
        ),
        RawRate(
            source_id="SRC-SCFI-001",
            publisher="Shanghai Containerized Freight Index",
            origin="CNSHA",
            destination="USLAX",
            mode="ocean",
            container="40HC",
            rate=Decimal("2400"),
            retrieved_at=now,
            source_url="https://example.test/scfi",
        ),
    ]


def _cache_row(timestamp: datetime):
    return SimpleNamespace(
        origin="CNSHA",
        destination="USLAX",
        mode="ocean",
        container="40HC",
        median_rate=Decimal("2425"),
        p25_rate=Decimal("2412.5"),
        p75_rate=Decimal("2437.5"),
        currency="USD",
        sample_size=2,
        confidence=Decimal("0.5"),
        quality_score=Decimal("0.5"),
        served_at=timestamp,
        valid_for=date.today(),
        provenance=[
            {
                "source_id": "SRC-WCI-001",
                "publisher": "Drewry World Container Index",
                "retrieved_at": timestamp.isoformat(),
                "source_url": "https://example.test/wci",
            }
        ],
        warnings=[],
    )


async def _request():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            "/v1/logistics/freight/rate"
            "?origin=CNSHA&destination=USLAX&mode=ocean&container=40HC"
        )


@pytest.mark.asyncio
async def test_p95_latency_under_200ms(api_client, monkeypatch):
    async def wci(client, lanes):
        return _rates()

    async def scfi(client, lanes):
        return _rates()[1:]

    monkeypatch.setattr(main, "fetch_wci_rates", wci)
    monkeypatch.setattr(main, "fetch_scfi_rates", scfi)
    cache = None

    async def lookup(*args):
        return cache

    async def store(*args, **kwargs):
        nonlocal cache
        cache = _cache_row(datetime.now(timezone.utc))

    monkeypatch.setattr(main, "get_cached_consensus", lookup)
    monkeypatch.setattr(main, "upsert_consensus", store)

    responses = await asyncio.gather(*[_request() for _ in range(100)])
    assert all(response.status_code == 200 for response in responses)
    latencies = sorted(response.json()["meta"]["api"]["latency_ms"] for response in responses)
    assert latencies[94] < 200


async def _always_miss(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_freshness_sla(api_client, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(days=2)
    row = _cache_row(old)
    async def stale_cache(*args):
        return row

    monkeypatch.setattr(main, "get_cached_consensus", stale_cache)
    async def old_wci(client, lanes):
        rates = _rates()
        return [rate.model_copy(update={"retrieved_at": old}) for rate in rates]

    async def old_scfi(client, lanes):
        rates = _rates()[1:]
        return [rate.model_copy(update={"retrieved_at": old}) for rate in rates]

    monkeypatch.setattr(main, "fetch_wci_rates", old_wci)
    monkeypatch.setattr(main, "fetch_scfi_rates", old_scfi)

    response = await _request()
    assert response.status_code == 200
    assert response.json()["meta"]["freshness"]["stale"] is True


@pytest.mark.asyncio
async def test_source_failover(api_client, monkeypatch):
    async def failed_wci(client, lanes):
        raise main.ScraperError("SRC-WCI-001", "test failure")

    monkeypatch.setattr(main, "fetch_wci_rates", failed_wci)
    async def scfi(client, lanes):
        return _rates()[1:]

    monkeypatch.setattr(main, "fetch_scfi_rates", scfi)
    monkeypatch.setattr(main, "get_cached_consensus", _always_miss)

    response = await _request()
    body = response.json()
    assert response.status_code == 200
    assert "source_down: SRC-WCI-001" in body["meta"]["warnings"]
    assert body["meta"]["trust"]["confidence"] < 1.0


@pytest.mark.asyncio
async def test_cache_hit(api_client, monkeypatch):
    calls = 0
    cached_row = None

    async def wci(client, lanes):
        nonlocal calls
        calls += 1
        return _rates()

    async def scfi(client, lanes):
        nonlocal calls
        calls += 1
        return _rates()[1:]

    async def cache_lookup(*args):
        return cached_row

    async def store_consensus(*args, **kwargs):
        nonlocal cached_row
        cached_row = SimpleNamespace(
            origin="CNSHA",
            destination="USLAX",
            mode="ocean",
            container="40HC",
            median_rate=Decimal("2425"),
            p25_rate=Decimal("2412.5"),
            p75_rate=Decimal("2437.5"),
            currency="USD",
            sample_size=2,
            confidence=Decimal("0.5"),
            quality_score=Decimal("0.5"),
            served_at=datetime.now(timezone.utc),
            valid_for=date.today(),
            provenance=[
                {
                    "source_id": "SRC-WCI-001",
                    "publisher": "Drewry World Container Index",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "source_url": "https://example.test/wci",
                }
            ],
            warnings=[],
        )

    monkeypatch.setattr(main, "fetch_wci_rates", wci)
    monkeypatch.setattr(main, "fetch_scfi_rates", scfi)
    monkeypatch.setattr(main, "get_cached_consensus", cache_lookup)
    monkeypatch.setattr(main, "upsert_consensus", store_consensus)

    first = await _request()
    second = await _request()
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["meta"]["api"]["cache_hit"] is True
    assert calls == 2
