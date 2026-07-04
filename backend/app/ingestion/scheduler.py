import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clients.eia_client import EIAClient
from app.clients.weather_client import WeatherClient
from app.config import get_settings
from app.db.session import get_connection
from app.ingestion.ingest import ensure_region_row, ingest_demand, ingest_generation_mix, ingest_weather_recent
from app.logging_config import configure_logging
from app.regions import REGIONS

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 3  # re-pull a rolling window since EIA revises recently published hours


def run_hourly_ingest() -> None:
    settings = get_settings()
    eia = EIAClient(settings.eia_api_key)
    weather = WeatherClient()

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=LOOKBACK_DAYS)

    with get_connection() as conn:
        for region_code in REGIONS:
            try:
                ensure_region_row(conn, region_code)
                ingest_demand(conn, eia, region_code, start.isoformat(), end.isoformat())
                ingest_generation_mix(conn, eia, region_code, start.isoformat(), end.isoformat())
                ingest_weather_recent(conn, weather, region_code, past_days=LOOKBACK_DAYS)
            except Exception:
                logger.exception("Hourly ingest failed for region %s", region_code)


def main() -> None:
    configure_logging()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_hourly_ingest, CronTrigger(minute=10), id="hourly_ingest")
    logger.info("Scheduler started — hourly ingest fires at :10 past every hour (UTC)")
    run_hourly_ingest()
    scheduler.start()


if __name__ == "__main__":
    main()
