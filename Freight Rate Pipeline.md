 
# Freight Rate Pipeline

Async FastAPI service that collects freight quotes, stores immutable snapshots in
PostgreSQL, and calculates a median consensus per route. SQLite is supported for
local development and tests.

## Run

```sh
python -m venv .venv && pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `DATABASE_URL` from `.env.example` for PostgreSQL, or use the default SQLite
URL. The production contract is `POST`/`GET /v1/logistics/freight/rate` plus
`GET /health`; interactive docs are at `/docs`.

Scrapers are adapters for the Freightos Baltic Index (`fbx.py`) and Drewry World
Container Index (`wci.py`). Add licensed providers by implementing `BaseScraper`
and registering them in `ScraperRegistry`; never commit credentials.
