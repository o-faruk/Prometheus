import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

COOLING_BASE_C = 18.0
HEATING_BASE_C = 18.0

FEATURE_COLUMNS = [
    "hours_ahead", "hour_of_day", "day_of_week", "month", "is_weekend", "is_holiday",
    "temperature_target", "temperature_target_sq", "cooling_degree_target", "heating_degree_target",
    "temperature_origin", "demand_origin", "demand_rolling_mean_24h_origin",
    "naive_24h_lag", "naive_168h_lag",
]
CATEGORICAL_COLUMNS = ["hour_of_day", "day_of_week", "month", "hours_ahead"]


def _holiday_dates(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return USFederalHolidayCalendar().holidays(start=start, end=end)


def build_feature_panel(
    demand: pd.Series,
    temperature: pd.Series,
    timezone: str,
    horizons: range = range(1, 25),
    origins: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """One row per (origin, hours_ahead). Every feature is computable using only data
    at/before `origin`, or calendar/weather knowledge of the target time (weather uses
    perfect-foresight temperature, same simplification as the Prophet backtest).

    Calendar features (hour/day/month/weekend/holiday) are computed in the region's local
    timezone, not UTC — demand cycles follow the wall clock people actually live by, and a
    naive UTC hour-of-day would drift against local time across DST transitions.
    """
    if origins is None:
        origins = demand.index

    demand_origin = demand.reindex(origins)
    temperature_origin = temperature.reindex(origins)
    rolling_mean_24h = demand.rolling(24, min_periods=24).mean().reindex(origins)

    holidays = _holiday_dates(origins.min() - pd.Timedelta(days=1), origins.max() + pd.Timedelta(days=8))

    frames = []
    for h in horizons:
        target_time = origins + pd.Timedelta(hours=h)
        target_local = target_time.tz_convert(timezone)

        target = demand.reindex(target_time).to_numpy()
        temp_target = temperature.reindex(target_time).to_numpy()
        naive_24h = demand.reindex(target_time - pd.Timedelta(hours=24)).to_numpy()
        naive_168h = demand.reindex(target_time - pd.Timedelta(hours=168)).to_numpy()

        frame = pd.DataFrame({
            "origin": origins,
            "target_time": target_time,
            "hours_ahead": h,
            "hour_of_day": target_local.hour,
            "day_of_week": target_local.dayofweek,
            "month": target_local.month,
            "is_weekend": (target_local.dayofweek >= 5).astype(int),
            "is_holiday": target_local.normalize().tz_localize(None).isin(holidays).astype(int),
            "temperature_target": temp_target,
            "temperature_target_sq": temp_target ** 2,
            "cooling_degree_target": np.maximum(temp_target - COOLING_BASE_C, 0),
            "heating_degree_target": np.maximum(HEATING_BASE_C - temp_target, 0),
            "temperature_origin": temperature_origin.to_numpy(),
            "demand_origin": demand_origin.to_numpy(),
            "demand_rolling_mean_24h_origin": rolling_mean_24h.to_numpy(),
            "naive_24h_lag": naive_24h,
            "naive_168h_lag": naive_168h,
            "target": target,
        })
        frames.append(frame)

    return pd.concat(frames, ignore_index=True)
