import lightgbm as lgb
import pandas as pd

from app.forecasting.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, build_feature_panel
from app.forecasting.models.base import Forecaster


class LightGBMForecaster(Forecaster):
    name = "lightgbm"

    def __init__(self, timezone: str) -> None:
        self._timezone = timezone
        self._model: lgb.LGBMRegressor | None = None

    def fit(self, demand: pd.Series, temperature: pd.Series) -> None:
        panel = build_feature_panel(demand, temperature, timezone=self._timezone)
        panel = panel.dropna(subset=FEATURE_COLUMNS + ["target"])

        X = _as_categorical(panel[FEATURE_COLUMNS])
        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=63,
            objective="regression",
            verbose=-1,
        )
        model.fit(X, panel["target"], categorical_feature=CATEGORICAL_COLUMNS)
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
            raise ValueError("LightGBMForecaster requires temperature_future for the forecast window")

        # temperature_history only needs to run through `origin`; future target-time
        # temperature comes from temperature_future (perfect-foresight, same as Prophet).
        temperature_full = pd.concat([temperature_history, temperature_future])
        panel = build_feature_panel(
            demand_history, temperature_full, timezone=self._timezone,
            horizons=range(1, horizon + 1), origins=pd.DatetimeIndex([origin]),
        )
        X = _as_categorical(panel[FEATURE_COLUMNS])
        predicted = self._model.predict(X)
        return pd.Series(predicted, index=pd.DatetimeIndex(panel["target_time"]))

    def feature_importances(self) -> pd.Series:
        importances = pd.Series(self._model.feature_importances_, index=FEATURE_COLUMNS)
        return importances.sort_values(ascending=False)


def _as_categorical(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy()
    for col in CATEGORICAL_COLUMNS:
        X[col] = X[col].astype("category")
    return X
