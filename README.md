# Freight Rate Pipeline

> A production-grade micro-service that aggregates **live ocean freight rates** from two independent
> industry benchmarks, cross-verifies them, and serves a single trusted rate to autonomous AI agents —
> with full lineage, freshness tracking, and automatic TTL cleanup.

---

## 🧭 What This Project Does (For the Non-Technical Reader)

Imagine you're an AI agent working for a shipping company. You need to know **"what does it cost today
to ship a container from Shanghai to Los Angeles?"**

You *could* just Google it — but different websites show different numbers, some are outdated,
some are paywalled, and you have no idea which one to trust. That's a problem when real money is on
the line.

**This project solves that problem.** It:

1. **Asks two trusted industry sources** for the current rate — the Drewry World Container Index (WCI)
   and the Shanghai Containerized Freight Index (SCFI).
2. **Compares their answers.** If they mostly agree, it returns the median value with high confidence.
   If one source gives a wildly different number (an "outlier"), it throws that number out and warns you.
3. **Stamps every response with a receipt** — when the data was fetched, how fresh it is, who published
   it, and how confident the system is in the answer.
4. **Auto-deletes old data** after 7 days so the database never grows stale or bloated.
5. **Never lies.** If a source is down, it says so explicitly. If both are down, it returns an error —
   it never silently hands back old data dressed up as fresh.

**The end result:** an AI agent (or a human) can call a single REST endpoint, get a trustworthy rate,
and know exactly where it came from.

---


**Data flow:**
1. Two scrapers fetch rates concurrently from OilPriceAPI (WCI + SCFI codes).
2. The consensus engine computes a median, applies a 1.5×IQR outlier filter, and produces a
   confidence score.
3. Raw observations, the computed consensus, and an audit log are all persisted in PostgreSQL JSONB columns.
4. A `pg_cron` job runs hourly to delete anything older than 7 days (TTL enforcement).
5. FastAPI serves the result in a standardized envelope with full provenance, freshness, and trust metadata.

---

## 🔧 Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| API framework | FastAPI + Uvicorn |
| HTTP client | httpx (async) |
| Database | PostgreSQL 15 (with `pg_cron`) |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Schema validation | Pydantic v2 |
| Testing | pytest + pytest-asyncio + pytest-cov |
| Container | Docker + Docker Compose |

---

## 📡 API

### `GET /health`

Quick liveness + DB ping.

```bash
curl.exe http://127.0.0.1:8000/health

Response:

json
{"status":"ok","db":"up"}
GET /v1/logistics/freight/rate
Returns a consensus freight rate for a given lane.

Query parameters:

Name	Type	Required	Default	Example
origin	string	yes	—	CNSHA
destination	string	yes	—	USLAX
mode	enum	no	ocean	ocean
container	enum	no	40HC	40HC
Example:

bash
curl.exe "http://127.0.0.1:8000/v1/logistics/freight/rate?origin=CNSHA&destination=USLAX&mode=ocean&container=40HC"
Response (HTTP 200):

json
{
  "data": {
    "origin": "CNSHA",
    "destination": "USLAX",
    "mode": "ocean",
    "container": "40HC",
    "median_rate": "4081.0",
    "currency": "USD",
    "valid_for": "2026-09-18",
    "sample_size": 2,
    "p25_rate": "3871.500",
    "p75_rate": "4290.500"
  },
  "meta": {
    "request_id": "req_8cf9ebfcc7234da6b614e4a84224f110",
    "product_id": "logistics.freight.rate.v1",
    "version": "1.0.0",
    "served_at": "2026-09-18T15:26:52.658327Z",
    "source_last_updated_at": "2026-09-17T16:30:45.355000Z",
    "freshness": {
      "age_seconds": 82567,
      "ttl_seconds": 604800,
      "stale": false
    },
    "provenance": [
      {
        "source_id": "SRC-WCI-001",
        "publisher": "Drewry World Container Index",
        "retrieved_at": "2026-09-17T16:30:45.355000Z",
        "source_url": "https://api.oilpriceapi.com/v1/prices/latest?by_code=DREWRY_WCI_USD"
      },
      {
        "source_id": "SRC-SCFI-001",
        "publisher": "Shanghai Containerized Freight Index",
        "retrieved_at": "2026-09-11T14:07:04.020000Z",
        "source_url": "https://api.oilpriceapi.com/v1/prices/latest?by_code=SCFI_INDEX"
      }
    ],
    "trust": {
      "confidence": 0.397,
      "quality_score": 0.397,
      "verified": true
    },
    "license": {
      "type": "commercial",
      "usage": "agent_runtime"
    },
    "api": {
      "latency_ms": 1170,
      "rate_limit": {"limit": 100, "window_seconds": 60}
    },
    "warnings": []
  }
}
Response (HTTP 503 — both sources down):

json
{
  "error": "upstream_unavailable",
  "error_code": "UPSTREAM_UNAVAILABLE",
  "details": {
    "sources_tried": ["SRC-WCI-001", "SRC-SCFI-001"],
    "sources_failed": ["SRC-WCI-001", "SRC-SCFI-001"],
    "reason": "both sources failed or returned no data"
  },
  "request_id": "req_...",
  "served_at": "2026-09-18T15:26:52Z"
}
Partial failure (one source down) still returns HTTP 200, but the failing source appears in
meta.warnings as "source_down: SRC-XXX" and trust.confidence is reduced.

🔐 Environment Variables
Create a .env file at the project root:

dotenv
DATABASE_URL=postgresql+asyncpg://freight:freight@localhost:5432/freight
FBX_BASE_URL=https://fbxtotal.com
WCI_BASE_URL=https://www.drewry.co.uk
TTL_SECONDS=604800
SCRAPE_INTERVAL_MINUTES=60
OILPRICE_API_KEY=your_oilpriceapi_key_here
⚠️ .env is gitignored. Never commit it. Use .env.example as the template.

Get a free OilPriceAPI key at https://oilpriceapi.com (50 requests/day on the free tier).

🚀 How to Run
Prerequisites
Windows 11 (or Linux/macOS with adjusted paths)

Docker Desktop running

Python 3.11+

Git (optional, for cloning)

1. Clone the repository
cmd
git clone https://github.com/YOUR_USERNAME/freight-rate-pipeline.git
cd freight-rate-pipeline
2. Set up the environment file
cmd
copy .env.example .env
notepad .env
Edit .env and set your real OILPRICE_API_KEY.

3. Create and activate a virtual environment
cmd
python -m venv .venv
.venv\Scripts\activate.bat
PowerShell:

powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
4. Install dependencies
cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pytest-cov
5. Start PostgreSQL (with pg_cron)
cmd
docker compose up -d db
Verify it's ready:

cmd
docker compose exec -T db pg_isready -U freight -d freight
6. Enable pg_cron and register the TTL purge job
cmd
docker compose exec -T db psql -U freight -d freight -c "CREATE EXTENSION IF NOT EXISTS pg_cron;"
docker compose exec -T db psql -U freight -d freight < scripts\pgcron_setup.sql
Verify:

cmd
docker compose exec -T db psql -U freight -d freight -c "SELECT jobname, schedule, active FROM cron.job;"
Expected:

text
          jobname           | schedule  | active
----------------------------+-----------+--------
 purge-expired-freight-data | 0 * * * * | t
7. Create the database tables
cmd
python -c "import asyncio; from app.db import init_models; asyncio.run(init_models())"
Verify:

cmd
docker compose exec -T db psql -U freight -d freight -c "\dt"
Expected: raw_freight_data, consensus_freight_rates, audit_log.

8. Run the test suite
cmd
pytest tests\ -v
Expected: 4 passed.

9. Verify live scrapers (optional)
cmd
python scripts\test_scrapers.py
Expected: one rate per source (WCI + SCFI).

10. Start the API
cmd
uvicorn app.main:app --reload --port 8000
11. Test the live endpoint
In a second terminal:

cmd
curl.exe http://127.0.0.1:8000/health
curl.exe "http://127.0.0.1:8000/v1/logistics/freight/rate?origin=CNSHA&destination=USLAX&mode=ocean&container=40HC"
You should get HTTP 200 with a median_rate populated.

🧪 Testing
cmd
pytest tests\ -v --cov=app
Covered:

Request validation and normalization (test_request_normalizes_lane)

Outlier rejection in consensus (test_consensus_rejects_outlier)

Source weight registration (test_scfi_source_has_full_weight)

OilPriceAPI scraper behavior with mocked HTTP (test_wci_and_scfi_use_oilprice_api)

🧹 TTL & Data Lifecycle
TTL: 7 days (configurable via TTL_SECONDS)

Purge job: hourly pg_cron job named purge-expired-freight-data

Tables purged: raw_freight_data, consensus_freight_rates, audit_log

Definition file: scripts/pgcron_setup.sql

To inspect run history:

sql
SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;

📁 Project Layout
text
freight-rate-pipeline/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + /v1/logistics/freight/rate
│   ├── db.py                # SQLAlchemy async engine, models, TTL helpers
│   ├── models.py            # Pydantic v2 schemas (request, response, envelope)
│   ├── consensus.py         # Median + IQR outlier rejection
│   └── scrapers/
│       ├── __init__.py      # ScraperError + exports
│       ├── fbx.py           # (legacy) Freightos scraper — not used in v1
│       ├── wci.py           # Drewry WCI via OilPriceAPI
│       └── scfi.py          # Shanghai SCFI via OilPriceAPI
├── tests/
│   ├── conftest.py
│   ├── test_contracts.py
│   └── test_oilprice_scrapers.py
├── scripts/
│   ├── pgcron_setup.sql
│   ├── test_scrapers.py     # Manual diagnostic script
│   └── run.sh               # (Linux/macOS helper)
├── docker/
│   └── init-pgcron.sql
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
📄 License
Academic project — for coursework use only.
