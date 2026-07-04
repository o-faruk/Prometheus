from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    AccuracyOut, AlertOut, AlertsOut, CurrentStateOut, ForecastOut, ForecastPointOut,
    FuelMixOut, GenerationMixOut, ModelAccuracyOut, PredictionHistoryOut,
    PredictionHistoryPointOut, RegionOut,
)
from app.db.session import get_connection
from app.regions import REGIONS

router = APIRouter()

LIVE_MODEL_NAME = "lightgbm"
RENEWABLE_FUEL_TYPES = {"SUN", "WND", "WAT", "GEO"}


def _require_region(region_code: str) -> None:
    if region_code not in REGIONS:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region_code}'")


@router.get("/regions", response_model=list[RegionOut])
def list_regions() -> list[RegionOut]:
    return [
        RegionOut(region_code=r.code, display_name=r.display_name, timezone=r.timezone)
        for r in REGIONS.values()
    ]


@router.get("/{region_code}/current", response_model=CurrentStateOut)
def get_current(region_code: str) -> CurrentStateOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT time, demand_mwh FROM demand WHERE region_code = %s AND demand_mwh IS NOT NULL "
            "ORDER BY time DESC LIMIT 1",
            (region_code,),
        )
        demand_row = cur.fetchone()
        if demand_row is None:
            raise HTTPException(status_code=404, detail="No data available yet for this region")

        cur.execute(
            "SELECT temperature_c FROM weather_observations WHERE region_code = %s AND time = %s LIMIT 1",
            (region_code, demand_row[0]),
        )
        temp_row = cur.fetchone()

    time_val, demand_val = demand_row
    minutes_ago = (datetime.now(timezone.utc) - time_val).total_seconds() / 60
    return CurrentStateOut(
        region_code=region_code,
        time=time_val,
        demand_mwh=demand_val,
        temperature_c=temp_row[0] if temp_row else None,
        minutes_since_update=minutes_ago,
    )


@router.get("/{region_code}/generation-mix", response_model=GenerationMixOut)
def get_generation_mix(region_code: str) -> GenerationMixOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max(time) FROM generation_mix WHERE region_code = %s",
            (region_code,),
        )
        latest_time = cur.fetchone()[0]
        if latest_time is None:
            raise HTTPException(status_code=404, detail="No generation-mix data available yet for this region")

        cur.execute(
            "SELECT fuel_type, generation_mwh FROM generation_mix "
            "WHERE region_code = %s AND time = %s AND generation_mwh IS NOT NULL",
            (region_code, latest_time),
        )
        rows = cur.fetchall()

    total = sum(v for _, v in rows) or 1.0
    renewable = sum(v for fuel, v in rows if fuel in RENEWABLE_FUEL_TYPES)
    fuels = [
        FuelMixOut(fuel_type=fuel, generation_mwh=v, share_pct=v / total * 100)
        for fuel, v in sorted(rows, key=lambda r: r[1], reverse=True)
    ]
    return GenerationMixOut(
        region_code=region_code,
        time=latest_time,
        total_mwh=total,
        renewable_share_pct=renewable / total * 100,
        fuels=fuels,
    )


@router.get("/{region_code}/forecast", response_model=ForecastOut)
def get_forecast(region_code: str) -> ForecastOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max(generated_at) FROM forecasts WHERE region_code = %s AND model_name = %s",
            (region_code, LIVE_MODEL_NAME),
        )
        generated_at = cur.fetchone()[0]
        if generated_at is None:
            raise HTTPException(status_code=404, detail="No forecast available yet for this region")

        cur.execute(
            """
            SELECT f.target_time, f.predicted_demand_mwh, d.demand_mwh
            FROM forecasts f
            LEFT JOIN demand d ON d.time = f.target_time AND d.region_code = f.region_code
            WHERE f.region_code = %s AND f.model_name = %s AND f.generated_at = %s
            ORDER BY f.target_time
            """,
            (region_code, LIVE_MODEL_NAME, generated_at),
        )
        rows = cur.fetchall()

    points = [
        ForecastPointOut(target_time=t, predicted_demand_mwh=p, actual_demand_mwh=a)
        for t, p, a in rows
    ]
    return ForecastOut(region_code=region_code, generated_at=generated_at, points=points)


@router.get("/{region_code}/accuracy", response_model=AccuracyOut)
def get_accuracy(region_code: str) -> AccuracyOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (model_name)
                model_name, mape, mae, rmse, n_forecasts, test_start, test_end, computed_at
            FROM model_accuracy
            WHERE region_code = %s
            ORDER BY model_name, computed_at DESC
            """,
            (region_code,),
        )
        rows = cur.fetchall()

    models = [
        ModelAccuracyOut(
            model_name=r[0], mape=r[1], mae=r[2], rmse=r[3], n_forecasts=r[4],
            test_start=r[5], test_end=r[6], computed_at=r[7],
        )
        for r in rows
    ]
    return AccuracyOut(region_code=region_code, models=models)


@router.get("/{region_code}/alerts", response_model=AlertsOut)
def get_alerts(region_code: str, include_normal: bool = False) -> AlertsOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(generated_at) FROM alerts WHERE region_code = %s", (region_code,))
        generated_at = cur.fetchone()[0]
        if generated_at is None:
            return AlertsOut(region_code=region_code, generated_at=None, alerts=[])

        query = (
            "SELECT target_time, level, forecasted_demand_mwh, percentile_rank, explanation "
            "FROM alerts WHERE region_code = %s AND generated_at = %s "
        )
        params: list = [region_code, generated_at]
        if not include_normal:
            query += "AND level != 'normal' "
        query += "ORDER BY target_time"
        cur.execute(query, params)
        rows = cur.fetchall()

    alerts = [
        AlertOut(target_time=r[0], level=r[1], forecasted_demand_mwh=r[2], percentile_rank=r[3], explanation=r[4])
        for r in rows
    ]
    return AlertsOut(region_code=region_code, generated_at=generated_at, alerts=alerts)


@router.get("/{region_code}/predictions-history", response_model=PredictionHistoryOut)
def get_predictions_history(region_code: str, limit: int = 72) -> PredictionHistoryOut:
    _require_region(region_code)
    with get_connection() as conn, conn.cursor() as cur:
        # Per resolved target_time, pick the forecast run made closest to 24h before it —
        # approximates "the day-ahead forecast for this hour", consistent with how every
        # other model comparison in this project is evaluated.
        cur.execute(
            """
            SELECT DISTINCT ON (f.target_time)
                f.target_time, f.predicted_demand_mwh, d.demand_mwh, f.generated_at
            FROM forecasts f
            JOIN demand d ON d.time = f.target_time AND d.region_code = f.region_code
            WHERE f.region_code = %s AND f.model_name = %s
              AND f.target_time <= now() AND d.demand_mwh IS NOT NULL
            ORDER BY f.target_time DESC,
                     ABS(EXTRACT(EPOCH FROM (f.generated_at - (f.target_time - interval '24 hours'))))
            LIMIT %s
            """,
            (region_code, LIVE_MODEL_NAME, limit),
        )
        rows = cur.fetchall()

    points = [
        PredictionHistoryPointOut(target_time=r[0], predicted_demand_mwh=r[1], actual_demand_mwh=r[2], generated_at=r[3])
        for r in rows
    ]
    return PredictionHistoryOut(region_code=region_code, points=list(reversed(points)))
