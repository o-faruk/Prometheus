import logging

import pandas as pd
from prophet import Prophet

from app.forecasting.models.base import Forecaster

logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


class ProphetForecaster(Forecaster):
    name = "prophet"

    def __init__(self, timezone: str) -> None:
        # Prophet's daily/weekly seasonality is fit against whatever clock 'ds' uses.
        # Feeding it raw UTC timestamps shifts every seasonal component by a fixed offset
        # AND makes that offset inconsistent across DST transitions, which is a genuine bug,
        # not just a labeling nit. Converting to local time first fixes both.
        self._timezone = timezone
        self._model: Prophet | None = None

    def fit(self, demand: pd.Series, temperature: pd.Series) -> None:
        df = pd.DataFrame({
            "ds": demand.index.tz_convert(self._timezone).tz_localize(None),
            "y": demand.to_numpy(),
            "temperature": temperature.reindex(demand.index).to_numpy(),
        })
        df = df.dropna()

        model = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
        model.add_regressor("temperature")
        model.fit(df)
        self._model = model

    def predict(
        self,
        origin: pd.Timestamp,
        horizon: int,
        demand_history: pd.Series,
        temperature_history: pd.Series,
        temperature_future: pd.Series | None = None,
    ) -> pd.Series:
        if temperature_future is None:
            raise ValueError("ProphetForecaster requires temperature_future for the forecast window")

        future_index = pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon, freq="h")
        future = pd.DataFrame({
            "ds": future_index.tz_convert(self._timezone).tz_localize(None),
            "temperature": temperature_future.reindex(future_index).to_numpy(),
        })
        forecast = self._model.predict(future)
        return pd.Series(forecast["yhat"].to_numpy(), index=future_index)
