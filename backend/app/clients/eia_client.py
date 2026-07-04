import logging
from typing import Iterator

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.clients.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

EIA_BASE_URL = "https://api.eia.gov/v2"
PAGE_SIZE = 5000


class EIAAPIError(Exception):
    pass


class EIAClient:
    def __init__(self, api_key: str, requests_per_hour: int = 4500) -> None:
        self._api_key = api_key
        self._session = requests.Session()
        self._limiter = RateLimiter(rate=requests_per_hour, per_seconds=3600)

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, EIAAPIError)),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, path: str, params: list[tuple[str, str]]) -> dict:
        self._limiter.acquire()
        query = [*params, ("api_key", self._api_key)]
        response = self._session.get(f"{EIA_BASE_URL}{path}", params=query, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            raise EIAAPIError(f"EIA API returned {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        return response.json()

    def fetch_series(
        self,
        route: str,
        respondent: str,
        data_columns: list[str],
        start: str,
        end: str,
        type_facet: str | None = None,
        frequency: str = "hourly",
    ) -> Iterator[dict]:
        offset = 0
        total = None
        while total is None or offset < total:
            params: list[tuple[str, str]] = [
                ("frequency", frequency),
                ("start", start),
                ("end", end),
                ("offset", str(offset)),
                ("length", str(PAGE_SIZE)),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "asc"),
                ("facets[respondent][]", respondent),
            ]
            if type_facet:
                params.append(("facets[type][]", type_facet))
            for column in data_columns:
                params.append(("data[]", column))

            payload = self._get(f"{route}/data/", params)
            body = payload["response"]
            if total is None:
                total = int(body["total"])
                logger.info(
                    "EIA %s: %d rows available for respondent=%s [%s..%s]",
                    route, total, respondent, start, end,
                )
            rows = body["data"]
            if not rows:
                break
            yield from rows
            offset += len(rows)

    def fetch_demand(self, respondent: str, start: str, end: str) -> Iterator[dict]:
        return self.fetch_series(
            route="/electricity/rto/region-data",
            respondent=respondent,
            data_columns=["value"],
            start=start,
            end=end,
            type_facet="D",
        )

    def fetch_demand_forecast(self, respondent: str, start: str, end: str) -> Iterator[dict]:
        return self.fetch_series(
            route="/electricity/rto/region-data",
            respondent=respondent,
            data_columns=["value"],
            start=start,
            end=end,
            type_facet="DF",
        )

    def fetch_generation_mix(self, respondent: str, start: str, end: str) -> Iterator[dict]:
        return self.fetch_series(
            route="/electricity/rto/fuel-type-data",
            respondent=respondent,
            data_columns=["value"],
            start=start,
            end=end,
        )
