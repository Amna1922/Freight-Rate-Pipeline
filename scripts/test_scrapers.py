from __future__ import annotations

import asyncio
import pathlib
import sys
import traceback

import httpx

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.scrapers import ScraperError, fetch_scfi_rates, fetch_wci_rates


LANES = [("CNSHA", "USLAX")]


async def run_scraper(name: str, fetcher, client: httpx.AsyncClient) -> None:
    print(f"\n{name}")
    try:
        rates = await fetcher(client, LANES)
        print(f"source_id={rates[0].source_id if rates else 'none'}")
        print(f"rates_returned={len(rates)}")
        for rate in rates:
            print(f"rate={rate.rate} {rate.currency} {rate.origin}->{rate.destination}")
    except ScraperError as exc:
        print(f"ScraperError: {exc}")
        traceback.print_exc()
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        print(f"Unexpected scraper error: {exc}")
        traceback.print_exc()


async def main() -> None:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        follow_redirects=True,
    ) as client:
        await run_scraper("WCI", fetch_wci_rates, client)
        await run_scraper("SCFI", fetch_scfi_rates, client)


if __name__ == "__main__":
    asyncio.run(main())
