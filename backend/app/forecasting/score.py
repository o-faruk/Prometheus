import argparse
import logging

import pandas as pd

from app.alerts.stress import generate_alert
from app.clients.weather_client import WeatherClient
from app.db.session import close_pool, get_connection
from app.forecasting.data import load_demand_series, load_weather_series
from app.forecasting.models.lightgbm_model import LightGBMForecaster
from app.logging_config import configure_logging
from app.regions import REGIONS

logger = logging.getLogger(__name__)

UPSERT_FORECAST = """
    INSERT INTO forecasts (generated_at, region_code, target_time, model_name, predicted_demand_mwh)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (generated_at, region_code, target_time, model_name) DO NOTHING
"""

UPSERT_ALERT = """
    INSERT INTO alerts
        (generated_at, region_code, target_time, level, forecasted_demand_mwh, percentile_rank, explanation)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (generated_at, region_code, target_time) DO NOTHING
"""


def _parse_forecast_time(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize("UTC")


def score_region(region_code: str, horizon: int = 24) -> None:
    region = REGIONS[region_code]
    demand_df = load_demand_series(region_code)
    temperature = load_weather_series(region_code)
    demand = demand_df["demand_mwh"]

    origin = demand.dropna().index.max()
    generated_at = pd.Timestamp.now(tz="UTC")

    model = LightGBMForecaster(timezone=region.timezone)
    model.fit(demand.loc[:origin], temperature.loc[:origin])

    weather_client = WeatherClient()
    forecast_records = weather_client.fetch_forecast_hourly(region.weather_lat, region.weather_lon, forecast_days=2)
    temperature_future = pd.Series(
        {_parse_forecast_time(r["time"]): r["temperature_c"] for r in forecast_records}
    ).sort_index()

    predicted = model.predict(
        origin, horizon,
        demand_history=demand.loc[:origin],
        temperature_history=temperature.loc[:origin],
        temperature_future=temperature_future,
    )

    forecast_rows = [
        (generated_at, region_code, target_time, model.name, float(value))
        for target_time, value in predicted.items()
    ]

    alert_rows = []
    for target_time, forecasted_demand in predicted.items():
        forecasted_temp = (
            float(temperature_future.loc[target_time]) if target_time in temperature_future.index else None
        )
        alert = generate_alert(
            region_code=region_code,
            timezone=region.timezone,
            target_time=target_time,
            forecasted_demand_mwh=float(forecasted_demand),
            demand_history=demand.loc[:origin],
            temperature_history=temperature.loc[:origin],
            forecasted_temperature_c=forecasted_temp,
        )
        alert_rows.append((
            generated_at, region_code, target_time, alert.level,
            alert.forecasted_demand_mwh, alert.percentile_rank, alert.explanation,
        ))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_FORECAST, forecast_rows)
            cur.executemany(UPSERT_ALERT, alert_rows)
        conn.commit()

    logger.info(
        "%s: scored %d forecast rows, %d alert rows (origin=%s, generated_at=%s)",
        region_code, len(forecast_rows), len(alert_rows), origin, generated_at,
    )


def score_all_regions() -> None:
    for region_code in REGIONS:
        try:
            score_region(region_code)
        except Exception:
            logger.exception("Scoring failed for region %s", region_code)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Compute and store live forecasts + alerts")
    parser.add_argument("--region", default=None, help="single region code; omit to run all regions")
    args = parser.parse_args()
    if args.region:
        score_region(args.region)
    else:
        score_all_regions()
    close_pool()


if __name__ == "__main__":
    main()
