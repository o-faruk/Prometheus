from dataclasses import dataclass

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

WATCH_PERCENTILE = 95
WARNING_PERCENTILE = 99
SIMILAR_EVENT_EXCLUSION_WINDOW = pd.Timedelta(hours=48)


@dataclass
class SimilarEvent:
    time: pd.Timestamp
    demand_mwh: float
    temperature_c: float


@dataclass
class StressAlert:
    region_code: str
    target_time: pd.Timestamp
    forecasted_demand_mwh: float
    level: str  # "normal" | "watch" | "warning"
    percentile_rank: float
    watch_threshold_mwh: float
    warning_threshold_mwh: float
    forecasted_temperature_c: float | None
    typical_temperature_c: float | None
    day_type: str
    similar_event: SimilarEvent | None
    explanation: str


def compute_thresholds(demand_history: pd.Series) -> dict[str, float]:
    """Stress is defined relative to this region's own observed demand distribution, not
    nameplate generation capacity (which we haven't ingested — see NOTES.md). 'warning' means
    this forecast would rank in the top 1% of hours we've ever recorded for this region."""
    clean = demand_history.dropna()
    return {
        "watch": float(clean.quantile(WATCH_PERCENTILE / 100)),
        "warning": float(clean.quantile(WARNING_PERCENTILE / 100)),
    }


def percentile_rank(demand_history: pd.Series, value: float) -> float:
    clean = demand_history.dropna()
    return float((clean < value).mean() * 100)


def classify(value: float, thresholds: dict[str, float]) -> str:
    if value >= thresholds["warning"]:
        return "warning"
    if value >= thresholds["watch"]:
        return "watch"
    return "normal"


def typical_temperature(temperature_history: pd.Series, timezone: str, target_time: pd.Timestamp) -> float | None:
    """Median temperature historically observed in this same local month and hour-of-day —
    the baseline 'normal' a forecast gets compared against for the '9 degrees above normal'
    framing in the alert explanation."""
    clean = temperature_history.dropna()
    if clean.empty:
        return None
    local_index = clean.index.tz_convert(timezone)
    target_local = target_time.tz_convert(timezone)
    mask = (local_index.month == target_local.month) & (local_index.hour == target_local.hour)
    matches = clean[mask]
    return float(matches.median()) if not matches.empty else None


def _day_type(timezone: str, target_time: pd.Timestamp) -> str:
    target_local = target_time.tz_convert(timezone)
    holidays = USFederalHolidayCalendar().holidays(
        start=target_local - pd.Timedelta(days=1), end=target_local + pd.Timedelta(days=1)
    )
    if target_local.normalize().tz_localize(None) in holidays:
        return "holiday"
    return "weekend" if target_local.dayofweek >= 5 else "weekday"


def find_similar_historical_event(
    demand_history: pd.Series,
    temperature_history: pd.Series,
    forecasted_temperature_c: float | None,
    target_time: pd.Timestamp,
    watch_threshold_mwh: float,
) -> SimilarEvent | None:
    """Among this region's own past stress-level hours (demand >= the watch threshold),
    find the one whose temperature most closely matches the forecast — 'similar to the
    [date] event' should mean a genuinely comparable past stress hour, not just any hot day."""
    if forecasted_temperature_c is None:
        return None

    candidates = demand_history[demand_history >= watch_threshold_mwh].dropna()
    too_close = (candidates.index >= target_time - SIMILAR_EVENT_EXCLUSION_WINDOW) & (
        candidates.index <= target_time + SIMILAR_EVENT_EXCLUSION_WINDOW
    )
    candidates = candidates[~too_close]
    if candidates.empty:
        return None

    candidate_temps = temperature_history.reindex(candidates.index).dropna()
    if candidate_temps.empty:
        return None

    closest_time = (candidate_temps - forecasted_temperature_c).abs().idxmin()
    return SimilarEvent(
        time=closest_time,
        demand_mwh=float(candidates.loc[closest_time]),
        temperature_c=float(candidate_temps.loc[closest_time]),
    )


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _render_explanation(
    region_code: str, timezone: str, target_time: pd.Timestamp, forecasted_demand_mwh: float,
    level: str, rank: float, forecasted_temperature_c: float | None, typical_temperature_c: float | None,
    day_type: str, similar_event: SimilarEvent | None,
) -> str:
    if level == "normal":
        return f"{region_code}: forecasted demand {forecasted_demand_mwh:,.0f} MWh — within normal range."

    target_local = target_time.tz_convert(timezone)
    parts = [
        f"{level.upper()}: {region_code} forecasted demand {forecasted_demand_mwh:,.0f} MWh at "
        f"{target_local:%Y-%m-%d %H:%M %Z}, ranking in the top {100 - rank:.1f}% of hours observed "
        f"for this region since 2019."
    ]

    if forecasted_temperature_c is not None and typical_temperature_c is not None:
        diff = forecasted_temperature_c - typical_temperature_c
        direction = "above" if diff >= 0 else "below"
        parts.append(
            f"Driven by a forecasted temperature of {forecasted_temperature_c:.0f}°C "
            f"({_c_to_f(forecasted_temperature_c):.0f}°F), {abs(diff):.0f}°C {direction} "
            f"the typical reading for this hour and month."
        )

    parts.append(f"Falls on a {day_type}.")

    if similar_event is not None:
        similar_local = similar_event.time.tz_convert(timezone)
        parts.append(
            f"Similar to {similar_local:%Y-%m-%d %H:%M %Z}, when demand reached "
            f"{similar_event.demand_mwh:,.0f} MWh at {similar_event.temperature_c:.0f}°C."
        )

    return " ".join(parts)


def generate_alert(
    region_code: str,
    timezone: str,
    target_time: pd.Timestamp,
    forecasted_demand_mwh: float,
    demand_history: pd.Series,
    temperature_history: pd.Series,
    forecasted_temperature_c: float | None = None,
) -> StressAlert:
    thresholds = compute_thresholds(demand_history)
    level = classify(forecasted_demand_mwh, thresholds)
    rank = percentile_rank(demand_history, forecasted_demand_mwh)
    typical_temp = typical_temperature(temperature_history, timezone, target_time)
    day_type = _day_type(timezone, target_time)

    similar_event = None
    if level != "normal":
        similar_event = find_similar_historical_event(
            demand_history, temperature_history, forecasted_temperature_c, target_time, thresholds["watch"]
        )

    explanation = _render_explanation(
        region_code, timezone, target_time, forecasted_demand_mwh, level, rank,
        forecasted_temperature_c, typical_temp, day_type, similar_event,
    )

    return StressAlert(
        region_code=region_code,
        target_time=target_time,
        forecasted_demand_mwh=forecasted_demand_mwh,
        level=level,
        percentile_rank=rank,
        watch_threshold_mwh=thresholds["watch"],
        warning_threshold_mwh=thresholds["warning"],
        forecasted_temperature_c=forecasted_temperature_c,
        typical_temperature_c=typical_temp,
        day_type=day_type,
        similar_event=similar_event,
        explanation=explanation,
    )
