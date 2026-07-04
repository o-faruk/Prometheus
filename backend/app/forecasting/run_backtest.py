import argparse
import logging
from pathlib import Path

import pandas as pd

from app.forecasting.backtest import summarize, summarize_by_horizon, walk_forward_backtest
from app.forecasting.data import load_demand_series, load_weather_series
from app.forecasting.metrics import mape
from app.forecasting.models.naive import SeasonalNaiveForecaster
from app.forecasting.models.prophet_model import ProphetForecaster
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def eia_forecast_accuracy(demand_df: pd.DataFrame, test_start: pd.Timestamp, test_end: pd.Timestamp) -> dict:
    window = demand_df.loc[test_start:test_end].dropna(subset=["demand_mwh", "demand_forecast_mwh"])
    return {
        "model": "eia_day_ahead_forecast",
        "n_forecasts": len(window),
        "mape": mape(window["demand_mwh"].to_numpy(), window["demand_forecast_mwh"].to_numpy()),
        "mae": None,
        "rmse": None,
    }


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Phase 2 backtest: naive vs Prophet vs EIA's own forecast")
    parser.add_argument("--region", default="CISO")
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--horizon", type=int, default=24)
    args = parser.parse_args()

    demand_df = load_demand_series(args.region)
    temperature = load_weather_series(args.region)
    demand = demand_df["demand_mwh"]

    test_end = demand.index.max() - pd.Timedelta(hours=args.horizon)
    test_start = test_end - pd.Timedelta(days=args.test_days)
    logger.info("Backtest window: %s to %s (%d days)", test_start, test_end, args.test_days)

    naive = SeasonalNaiveForecaster()
    naive_results = walk_forward_backtest(
        naive, demand, temperature, test_start, test_end, horizon=args.horizon, refit_interval_days=1
    )

    prophet_model = ProphetForecaster()
    prophet_results = walk_forward_backtest(
        prophet_model, demand, temperature, test_start, test_end, horizon=args.horizon, refit_interval_days=7
    )

    summaries = [
        summarize(naive.name, naive_results),
        summarize(prophet_model.name, prophet_results),
        eia_forecast_accuracy(demand_df, test_start, test_end),
    ]

    print("\n=== Phase 2 backtest: overall (1-24h-ahead forecasts, 90-day test window) ===")
    for r in summaries:
        mae_str = f"{r['mae']:.1f}" if r["mae"] is not None else "n/a"
        rmse_str = f"{r['rmse']:.1f}" if r["rmse"] is not None else "n/a"
        print(f"{r['model']:28s}  MAPE={r['mape']:.2f}%  MAE={mae_str}  RMSE={rmse_str}  n={r['n_forecasts']}")

    naive_hz = summarize_by_horizon(naive.name, naive_results).set_index("hours_ahead")["mape"]
    prophet_hz = summarize_by_horizon(prophet_model.name, prophet_results).set_index("hours_ahead")["mape"]
    print("\n=== MAPE by hours-ahead ===")
    for h in [1, 6, 12, 18, 24]:
        print(f"h={h:2d}  naive={naive_hz.loc[h]:.2f}%  prophet={prophet_hz.loc[h]:.2f}%")

    Path("reports").mkdir(exist_ok=True)
    naive_results.to_csv("reports/backtest_naive.csv", index=False)
    prophet_results.to_csv("reports/backtest_prophet.csv", index=False)
    logger.info("Wrote reports/backtest_naive.csv and reports/backtest_prophet.csv")


if __name__ == "__main__":
    main()
