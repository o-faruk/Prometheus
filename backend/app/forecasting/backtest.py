import logging

import pandas as pd

from app.forecasting.metrics import mae, mape, rmse
from app.forecasting.models.base import Forecaster

logger = logging.getLogger(__name__)


def walk_forward_backtest(
    forecaster: Forecaster,
    demand: pd.Series,
    temperature: pd.Series,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    horizon: int = 24,
    refit_interval_days: int = 7,
    step_days: int = 1,
) -> pd.DataFrame:
    """Each `origin` yields one forecast covering hours origin+1 .. origin+horizon.
    The model is refit only every `refit_interval_days`, reused across origins in between
    (mirrors a periodic-retrain, continuous-operation deployment instead of retraining hourly)."""
    records = []
    origin = test_start
    last_refit: pd.Timestamp | None = None

    while origin + pd.Timedelta(hours=horizon) <= test_end:
        if last_refit is None or (origin - last_refit) >= pd.Timedelta(days=refit_interval_days):
            forecaster.fit(demand.loc[:origin], temperature.loc[:origin])
            last_refit = origin
            logger.info("%s: refit using data through %s", forecaster.name, origin)

        future_index = pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon, freq="h")
        temperature_future = temperature.reindex(future_index)
        predicted = forecaster.predict(origin, horizon, temperature_future=temperature_future)
        actual = demand.reindex(future_index)

        for hours_ahead, t in enumerate(future_index, start=1):
            records.append({
                "origin": origin,
                "target_time": t,
                "hours_ahead": hours_ahead,
                "predicted": predicted.loc[t],
                "actual": actual.loc[t],
            })

        origin += pd.Timedelta(days=step_days)

    return pd.DataFrame.from_records(records).dropna(subset=["predicted", "actual"])


def summarize(model_name: str, results: pd.DataFrame) -> dict:
    actual = results["actual"].to_numpy()
    predicted = results["predicted"].to_numpy()
    return {
        "model": model_name,
        "n_forecasts": len(results),
        "mape": mape(actual, predicted),
        "mae": mae(actual, predicted),
        "rmse": rmse(actual, predicted),
    }


def summarize_by_horizon(model_name: str, results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for hours_ahead, group in results.groupby("hours_ahead"):
        row = summarize(model_name, group)
        row["hours_ahead"] = hours_ahead
        rows.append(row)
    return pd.DataFrame(rows)
