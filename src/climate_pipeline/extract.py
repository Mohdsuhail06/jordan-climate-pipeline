"""Extract step: call the Open-Meteo APIs and keep a raw copy of every response."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from climate_pipeline.config import (
    AIR_QUALITY_API_URL,
    DAILY_WEATHER_VARS,
    HOURLY_AIR_VARS,
    TIMEZONE,
    WEATHER_API_URL,
    City,
)

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 30


class ExtractError(RuntimeError):
    """Raised when an API call fails or returns an error payload."""


class HttpSession(Protocol):
    """The small part of `requests.Session` we use (lets tests pass a fake)."""

    def get(self, url: str, params: dict, timeout: float): ...


def build_session(retries: int = 3, backoff: float = 1.0) -> requests.Session:
    """Create an HTTP session that retries on rate limits (429) and server errors (5xx).

    Waits grow exponentially between attempts (`backoff` * 2^n seconds).
    """
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "jordan-climate-pipeline/1.0"
    return session


def _get_json(session: HttpSession, url: str, params: dict, city: City) -> dict:
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ExtractError(f"{city.city_id}: request failed ({exc})") from exc

    if response.status_code >= 400 or payload.get("error"):
        reason = payload.get("reason", f"HTTP {response.status_code}")
        raise ExtractError(f"{city.city_id}: API error - {reason}")
    return payload


def _base_params(city: City, start: dt.date, end: dt.date) -> dict:
    return {
        "latitude": city.latitude,
        "longitude": city.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": TIMEZONE,
    }


def fetch_weather(session: HttpSession, city: City, start: dt.date, end: dt.date) -> dict:
    """Download daily historical weather for one city and date range."""
    params = _base_params(city, start, end) | {"daily": ",".join(DAILY_WEATHER_VARS)}
    log.info("Fetching weather for %s %s..%s", city.city_id, start, end)
    return _get_json(session, WEATHER_API_URL, params, city)


def fetch_air_quality(session: HttpSession, city: City, start: dt.date, end: dt.date) -> dict:
    """Download hourly air-quality readings for one city and date range."""
    params = _base_params(city, start, end) | {"hourly": ",".join(HOURLY_AIR_VARS)}
    log.info("Fetching air quality for %s %s..%s", city.city_id, start, end)
    return _get_json(session, AIR_QUALITY_API_URL, params, city)


def save_raw(
    payload: dict, raw_dir: Path, source: str, city_id: str, start: dt.date, end: dt.date
) -> Path:
    """Store the untouched API response (the "raw" / bronze layer) so runs can be replayed."""
    path = Path(raw_dir) / source / city_id / f"{start.isoformat()}_{end.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
