from datetime import datetime

from pydantic import BaseModel


class RegionOut(BaseModel):
    region_code: str
    display_name: str
    timezone: str


class CurrentStateOut(BaseModel):
    region_code: str
    time: datetime
    demand_mwh: float | None
    temperature_c: float | None
    minutes_since_update: float


class ForecastPointOut(BaseModel):
    target_time: datetime
    predicted_demand_mwh: float
    actual_demand_mwh: float | None


class ForecastOut(BaseModel):
    region_code: str
    generated_at: datetime
    points: list[ForecastPointOut]


class ModelAccuracyOut(BaseModel):
    model_name: str
    mape: float
    mae: float | None
    rmse: float | None
    n_forecasts: int
    test_start: datetime
    test_end: datetime
    computed_at: datetime


class AccuracyOut(BaseModel):
    region_code: str
    models: list[ModelAccuracyOut]


class AlertOut(BaseModel):
    target_time: datetime
    level: str
    forecasted_demand_mwh: float
    percentile_rank: float | None
    explanation: str


class AlertsOut(BaseModel):
    region_code: str
    generated_at: datetime | None
    alerts: list[AlertOut]


class PredictionHistoryPointOut(BaseModel):
    target_time: datetime
    predicted_demand_mwh: float
    actual_demand_mwh: float
    generated_at: datetime


class PredictionHistoryOut(BaseModel):
    region_code: str
    points: list[PredictionHistoryPointOut]


class FuelMixOut(BaseModel):
    fuel_type: str
    generation_mwh: float
    share_pct: float


class GenerationMixOut(BaseModel):
    region_code: str
    time: datetime
    total_mwh: float
    renewable_share_pct: float
    fuels: list[FuelMixOut]
