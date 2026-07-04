import logging

import pandas as pd

from app.db.session import get_connection

logger = logging.getLogger(__name__)

MAX_INTERPOLATION_GAP_HOURS = 3


def _fill_small_gaps(series: pd.Series, column_name: str) -> pd.Series:
    missing_before = series.isna().sum()
    if missing_before == 0:
        return series

    filled = series.interpolate(method="linear", limit=MAX_INTERPOLATION_GAP_HOURS)
    still_missing = filled.isna().sum()
    logger.warning(
        "%s: interpolated %d/%d missing hourly values (gaps <= %dh); %d remain missing",
        column_name, missing_before - still_missing, missing_before,
        MAX_INTERPOLATION_GAP_HOURS, still_missing,
    )
    return filled


def load_demand_series(region_code: str) -> pd.DataFrame:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT time, demand_mwh, demand_forecast_mwh FROM demand "
            "WHERE region_code = %s ORDER BY time",
            (region_code,),
        )
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=["time", "demand_mwh", "demand_forecast_mwh"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").asfreq("h")
    df["demand_mwh"] = _fill_small_gaps(df["demand_mwh"], "demand_mwh")
    return df


def load_weather_series(region_code: str) -> pd.Series:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT time, temperature_c FROM weather_observations "
            "WHERE region_code = %s ORDER BY time",
            (region_code,),
        )
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=["time", "temperature_c"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    series = df.set_index("time")["temperature_c"].asfreq("h")
    return _fill_small_gaps(series, "temperature_c")
