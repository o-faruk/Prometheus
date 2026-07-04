# Prometheus

Real-time electricity grid monitoring and stress-forecasting system. Ingests live U.S. grid
data (demand, generation mix, wholesale pricing) from public APIs, forecasts grid stress hours
ahead using multiple compared forecasting models, and tracks its own prediction accuracy
transparently over time.

## Status

Phase 1 (data pipeline foundation) — in progress. CAISO demand, generation mix, and weather
are flowing into TimescaleDB.

## Local setup

1. Copy `.env.example` to `.env` and set `EIA_API_KEY` (free, instant — register at
   https://www.eia.gov/opendata/register.php).
2. Start the database: `docker compose up -d`
3. Create a virtualenv and install dependencies:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
4. From `backend/`, backfill historical data:
   ```
   cd backend
   ../.venv/bin/python -m app.ingestion.backfill --region CISO --start 2019-01-01
   ```
5. Run the hourly ingestion scheduler:
   ```
   ../.venv/bin/python -m app.ingestion.scheduler
   ```

## Architecture

- **Data sources:** EIA API v2 (hourly demand, day-ahead demand forecast, and generation mix
  by fuel type, per balancing authority) and Open-Meteo (free, keyless historical + forecast
  weather).
- **Storage:** TimescaleDB (Postgres + hypertables) via Docker Compose.
- **Regions:** `backend/app/regions.py` is a small registry — adding ERCOT or PJM is a config
  entry, not new ingestion code.
