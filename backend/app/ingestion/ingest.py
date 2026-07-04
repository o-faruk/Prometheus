import logging
from datetime import datetime, timezone

import psycopg

from app.clients.eia_client import EIAClient
from app.clients.weather_client import WeatherClient
from app.regions import REGIONS

logger = logging.getLogger(__name__)

UPSERT_DEMAND_ACTUAL = """
    INSERT INTO demand (time, region_code, demand_mwh)
    VALUES (%s, %s, %s)
    ON CONFLICT (time, region_code) DO UPDATE SET demand_mwh = EXCLUDED.demand_mwh
"""

UPSERT_DEMAND_FORECAST = """
    INSERT INTO demand (time, region_code, demand_forecast_mwh)
    VALUES (%s, %s, %s)
    ON CONFLICT (time, region_code) DO UPDATE SET demand_forecast_mwh = EXCLUDED.demand_forecast_mwh
"""

UPSERT_GENERATION = """
    INSERT INTO generation_mix (time, region_code, fuel_type, generation_mwh)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (time, region_code, fuel_type) DO UPDATE SET generation_mwh = EXCLUDED.generation_mwh
"""

# Same `source` for both historical and recent pulls is deliberate: Open-Meteo's
# reanalysis archive lags ~5 days behind real time, so recent hours are first filled
# from the forecast API's estimate, then silently upgraded once the archive catches up.
UPSERT_WEATHER = """
    INSERT INTO weather_observations (time, region_code, temperature_c, source)
    VALUES (%s, %s, %s, 'open-meteo')
    ON CONFLICT (time, region_code, source) DO UPDATE SET temperature_c = EXCLUDED.temperature_c
"""


def _parse_eia_period(period: str) -> datetime:
    return datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


def _parse_iso_hour(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def ingest_demand(conn: psycopg.Connection, eia: EIAClient, region_code: str, start: str, end: str) -> int:
    rows = [
        (_parse_eia_period(r["period"]), region_code, float(r["value"]))
        for r in eia.fetch_demand(region_code, start, end)
        if r.get("value") is not None
    ]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_DEMAND_ACTUAL, rows)

    forecast_rows = [
        (_parse_eia_period(r["period"]), region_code, float(r["value"]))
        for r in eia.fetch_demand_forecast(region_code, start, end)
        if r.get("value") is not None
    ]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_DEMAND_FORECAST, forecast_rows)

    conn.commit()
    logger.info(
        "Ingested %d actual + %d forecast demand rows for %s", len(rows), len(forecast_rows), region_code
    )
    return len(rows) + len(forecast_rows)


def ingest_generation_mix(conn: psycopg.Connection, eia: EIAClient, region_code: str, start: str, end: str) -> int:
    rows = [
        (_parse_eia_period(r["period"]), region_code, r["fueltype"], float(r["value"]))
        for r in eia.fetch_generation_mix(region_code, start, end)
        if r.get("value") is not None
    ]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_GENERATION, rows)
    conn.commit()
    logger.info("Ingested %d generation-mix rows for %s", len(rows), region_code)
    return len(rows)


def ingest_weather_historical(
    conn: psycopg.Connection, weather: WeatherClient, region_code: str, start_date: str, end_date: str
) -> int:
    region = REGIONS[region_code]
    records = weather.fetch_historical_hourly(region.weather_lat, region.weather_lon, start_date, end_date)
    rows = [(_parse_iso_hour(r["time"]), region_code, r["temperature_c"]) for r in records]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_WEATHER, rows)
    conn.commit()
    logger.info("Ingested %d historical weather rows for %s", len(rows), region_code)
    return len(rows)


def ingest_weather_recent(
    conn: psycopg.Connection, weather: WeatherClient, region_code: str, past_days: int = 3
) -> int:
    region = REGIONS[region_code]
    records = weather.fetch_recent_hourly(region.weather_lat, region.weather_lon, past_days)
    rows = [(_parse_iso_hour(r["time"]), region_code, r["temperature_c"]) for r in records]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_WEATHER, rows)
    conn.commit()
    logger.info("Ingested %d recent weather rows for %s", len(rows), region_code)
    return len(rows)
