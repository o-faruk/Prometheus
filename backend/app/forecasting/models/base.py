from abc import ABC, abstractmethod

import pandas as pd


class Forecaster(ABC):
    name: str

    @abstractmethod
    def fit(self, demand: pd.Series, temperature: pd.Series) -> None:
        """Fit using all data up to and including the last timestamp in `demand`."""

    @abstractmethod
    def predict(
        self,
        origin: pd.Timestamp,
        horizon: int,
        demand_history: pd.Series,
        temperature_history: pd.Series,
        temperature_future: pd.Series | None = None,
    ) -> pd.Series:
        """Forecast `horizon` hourly steps starting at origin + 1h.

        `demand_history`/`temperature_history` run through `origin` and may be more recent
        than the data the model was last fit on (fit can happen on a slower cadence than
        predict) — feature-based models should use these for any lag/recency features so
        they reflect the true forecast-time state, not a stale training snapshot.
        """
