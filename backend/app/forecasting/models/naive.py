import pandas as pd

from app.forecasting.models.base import Forecaster


class SeasonalNaiveForecaster(Forecaster):
    """forecast(t) = actual(t - season_length). Default season_length=168h (same hour, last week)."""

    name = "seasonal_naive_168h"

    def __init__(self, season_length: int = 168) -> None:
        self.season_length = season_length
        self._history: pd.Series | None = None

    def fit(self, demand: pd.Series, temperature: pd.Series) -> None:
        self._history = demand

    def predict(self, origin: pd.Timestamp, horizon: int, temperature_future: pd.Series | None = None) -> pd.Series:
        future_index = pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon, freq="h")
        lookback_index = future_index - pd.Timedelta(hours=self.season_length)
        values = self._history.reindex(lookback_index).to_numpy()
        return pd.Series(values, index=future_index)
