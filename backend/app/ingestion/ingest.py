import logging
from datetime import datetime, timezone

import psycopg

from app.clients.eia_client import EIAClient
from app.clients.weather_client import WeatherClient
from app.regions import REGIONS

logger = logging.getLogger(__name__)

# Generous enough to never reject genuine data (PJM, the largest US RTO, has an
# all-time record around 165,000 MWh/hour) but catches source-data corruption. Found via
# real EIA glitches: PJM returned values ranging from ~192,000 up to ~2.1 billion MWh for
# a handful of hours — sanity bounds on external data are not optional, "authoritative"
# sources can still return garbage.
MAX_PLAUSIBLE_DEMAND_MWH = 170_000
MAX_PLAUSIBLE_GENERATION_MWH = 150_000

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


UPSERT_REGION = """
    INSERT INTO regions (region_code, display_name, timezone, weather_lat, weather_lon)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (region_code) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        timezone = EXCLUDED.timezone,
        weather_lat = EXCLUDED.weather_lat,
        weather_lon = EXCLUDED.weather_lon
"""


def _parse_eia_period(period: str) -> datetime:
    return datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


def _parse_iso_hour(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def ensure_region_row(conn: psycopg.Connection, region_code: str) -> None:
    """`REGIONS` in regions.py is the single source of truth; this syncs it into the
    `regions` table (required for the FK on demand/generation_mix/weather_observations)
    so adding a region is purely a regions.py edit, never a manual DB step."""
    region = REGIONS[region_code]
    with conn.cursor() as cur:
        cur.execute(
            UPSERT_REGION,
            (region.code, region.display_name, region.timezone, region.weather_lat, region.weather_lon),
        )
    conn.commit()


def _implausible(value: float, max_value: float) -> bool:
    return value <= 0 or value > max_value


def ingest_demand(conn: psycopg.Connection, eia: EIAClient, region_code: str, start: str, end: str) -> int:
    rows = []
    rejected = 0
    for r in eia.fetch_demand(region_code, start, end):
        if r.get("value") is None:
            continue
        value = float(r["value"])
        if _implausible(value, MAX_PLAUSIBLE_DEMAND_MWH):
            rejected += 1
            continue
        rows.append((_parse_eia_period(r["period"]), region_code, value))
    if rejected:
        logger.warning("%s: rejected %d implausible actual-demand values from EIA", region_code, rejected)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_DEMAND_ACTUAL, rows)

    forecast_rows = []
    rejected = 0
    for r in eia.fetch_demand_forecast(region_code, start, end):
        if r.get("value") is None:
            continue
        value = float(r["value"])
        if _implausible(value, MAX_PLAUSIBLE_DEMAND_MWH):
            rejected += 1
            continue
        forecast_rows.append((_parse_eia_period(r["period"]), region_code, value))
    if rejected:
        logger.warning("%s: rejected %d implausible demand-forecast values from EIA", region_code, rejected)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_DEMAND_FORECAST, forecast_rows)

    conn.commit()
    logger.info(
        "Ingested %d actual + %d forecast demand rows for %s", len(rows), len(forecast_rows), region_code
    )
    return len(rows) + len(forecast_rows)


def ingest_generation_mix(conn: psycopg.Connection, eia: EIAClient, region_code: str, start: str, end: str) -> int:
    rows = []
    rejected = 0
    for r in eia.fetch_generation_mix(region_code, start, end):
        if r.get("value") is None:
            continue
        value = float(r["value"])
        if _implausible(value, MAX_PLAUSIBLE_GENERATION_MWH):
            rejected += 1
            continue
        rows.append((_parse_eia_period(r["period"]), region_code, r["fueltype"], value))
    if rejected:
        logger.warning("%s: rejected %d implausible generation-mix values from EIA", region_code, rejected)
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
