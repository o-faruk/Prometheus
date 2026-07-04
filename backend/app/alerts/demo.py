import argparse
import logging

import pandas as pd

from app.alerts.stress import generate_alert
from app.db.session import close_pool
from app.forecasting.data import load_demand_series, load_weather_series
from app.forecasting.models.lightgbm_model import LightGBMForecaster
from app.logging_config import configure_logging
from app.regions import REGIONS

logger = logging.getLogger(__name__)


def demo_region(region_code: str) -> None:
    region = REGIONS[region_code]
    demand_df = load_demand_series(region_code)
    temperature = load_weather_series(region_code)
    demand = demand_df["demand_mwh"]

    # Find this region's real historical peak-demand hour, then simulate standing
    # 24h before it — proving alerts fire correctly against a genuine past stress event,
    # not a synthetic one. Excludes the last 30 days so there's a full day of real
    # post-event history for the "similar event" lookup to search over if needed.
    searchable = demand.loc[:demand.index.max() - pd.Timedelta(days=30)]
    peak_time = searchable.idxmax()
    origin = peak_time - pd.Timedelta(hours=24)

    logger.info("%s: real historical peak %.0f MWh at %s (local %s)",
                region_code, searchable.loc[peak_time], peak_time,
                peak_time.tz_convert(region.timezone))

    model = LightGBMForecaster(timezone=region.timezone)
    model.fit(demand.loc[:origin], temperature.loc[:origin])

    future_index = pd.date_range(origin + pd.Timedelta(hours=1), periods=24, freq="h")
    temperature_future = temperature.reindex(future_index)
    forecast = model.predict(
        origin, 24,
        demand_history=demand.loc[:origin],
        temperature_history=temperature.loc[:origin],
        temperature_future=temperature_future,
    )

    forecasted_demand = float(forecast.loc[peak_time])
    actual_demand = float(demand.loc[peak_time])
    forecasted_temp = float(temperature.loc[peak_time]) if peak_time in temperature.index else None

    alert = generate_alert(
        region_code=region_code,
        timezone=region.timezone,
        target_time=peak_time,
        forecasted_demand_mwh=forecasted_demand,
        demand_history=demand.loc[:origin],
        temperature_history=temperature.loc[:origin],
        forecasted_temperature_c=forecasted_temp,
    )

    print(f"\n=== {region.display_name} ({region_code}) ===")
    print(f"Standing at {origin} (24h before the real historical peak), forecasting {peak_time}")
    print(f"Model forecast: {forecasted_demand:,.0f} MWh   |   Actual (what really happened): {actual_demand:,.0f} MWh")
    print(f"Alert level: {alert.level.upper()}")
    print(f"Watch threshold: {alert.watch_threshold_mwh:,.0f} MWh   Warning threshold: {alert.warning_threshold_mwh:,.0f} MWh")
    print(alert.explanation)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Demonstrate stress alerts against real historical peak events")
    parser.add_argument("--region", default=None, help="single region code; omit to run all regions")
    args = parser.parse_args()

    regions = [args.region] if args.region else list(REGIONS)
    for region_code in regions:
        demo_region(region_code)
    close_pool()


if __name__ == "__main__":
    main()
