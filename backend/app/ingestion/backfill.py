import argparse
import logging
from datetime import datetime, timezone

from app.clients.eia_client import EIAClient
from app.clients.weather_client import WeatherClient
from app.config import get_settings
from app.db.session import close_pool, get_connection
from app.ingestion.ingest import ensure_region_row, ingest_demand, ingest_generation_mix, ingest_weather_historical
from app.logging_config import configure_logging
from app.regions import REGIONS

logger = logging.getLogger(__name__)

DEFAULT_START = "2019-01-01"  # EIA-930 hourly coverage begins mid-2018; 2019 gives a clean full year


def backfill_region(region_code: str, start: str, end: str) -> None:
    if region_code not in REGIONS:
        raise ValueError(f"Unknown region {region_code}; add it to app.regions.REGIONS first")

    settings = get_settings()
    eia = EIAClient(settings.eia_api_key)
    weather = WeatherClient()

    with get_connection() as conn:
        ensure_region_row(conn, region_code)
        demand_rows = ingest_demand(conn, eia, region_code, start, end)
        generation_rows = ingest_generation_mix(conn, eia, region_code, start, end)
        weather_rows = ingest_weather_historical(conn, weather, region_code, start, end)
    close_pool()

    logger.info(
        "Backfill complete for %s [%s..%s]: %d demand rows, %d generation rows, %d weather rows",
        region_code, start, end, demand_rows, generation_rows, weather_rows,
    )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Backfill historical grid + weather data")
    parser.add_argument("--region", default="CISO")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()
    backfill_region(args.region, args.start, args.end)


if __name__ == "__main__":
    main()
