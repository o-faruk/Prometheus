import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherClient:
    def __init__(self) -> None:
        self._session = requests.Session()

    @retry(wait=wait_exponential_jitter(initial=1, max=30), stop=stop_after_attempt(5), reraise=True)
    def _get(self, url: str, params: dict) -> dict:
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_historical_hourly(self, lat: float, lon: float, start_date: str, end_date: str) -> list[dict]:
        payload = self._get(
            ARCHIVE_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": "temperature_2m",
                "timezone": "UTC",
            },
        )
        return self._to_rows(payload)

    def fetch_recent_hourly(self, lat: float, lon: float, past_days: int = 3) -> list[dict]:
        payload = self._get(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "past_days": past_days,
                "forecast_days": 1,
                "hourly": "temperature_2m",
                "timezone": "UTC",
            },
        )
        return self._to_rows(payload)

    def fetch_forecast_hourly(self, lat: float, lon: float, forecast_days: int = 7) -> list[dict]:
        """Real forward-looking weather forecast (not perfect-foresight actuals) — for live
        alerting, where we genuinely don't know the future temperature yet. Open-Meteo
        supports up to 16 forecast days; capped lower here since forecast skill degrades
        fast past ~7 days and the alert horizon is 24h anyway."""
        payload = self._get(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "forecast_days": forecast_days,
                "hourly": "temperature_2m",
                "timezone": "UTC",
            },
        )
        return self._to_rows(payload)

    @staticmethod
    def _to_rows(payload: dict) -> list[dict]:
        hourly = payload["hourly"]
        return [
            {"time": t, "temperature_c": v}
            for t, v in zip(hourly["time"], hourly["temperature_2m"])
            if v is not None
        ]
