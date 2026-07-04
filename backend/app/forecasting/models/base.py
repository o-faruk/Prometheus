from abc import ABC, abstractmethod

import pandas as pd


class Forecaster(ABC):
    name: str

    @abstractmethod
    def fit(self, demand: pd.Series, temperature: pd.Series) -> None:
        """Fit using all data up to and including the last timestamp in `demand`."""

    @abstractmethod
    def predict(self, origin: pd.Timestamp, horizon: int, temperature_future: pd.Series | None = None) -> pd.Series:
        """Forecast `horizon` hourly steps starting at origin + 1h."""
