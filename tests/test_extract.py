"""Tests for the extract step. A fake HTTP session is used, so no real network calls happen."""

from __future__ import annotations

import datetime as dt
import json

import pytest
import requests

from climate_pipeline.extract import (
    ExtractError,
    build_session,
    fetch_air_quality,
    fetch_weather,
    save_raw,
)
from tests.conftest import make_weather_payload


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Records every request and returns a canned response."""

    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: float) -> FakeResponse:
        self.calls.append((url, params))
        return self.response


START, END = dt.date(2025, 1, 1), dt.date(2025, 1, 31)


def test_fetch_weather_sends_city_coordinates_and_dates(amman):
    session = FakeSession(FakeResponse(make_weather_payload(["2025-01-01"])))

    payload = fetch_weather(session, amman, START, END)

    url, params = session.calls[0]
    assert "archive-api.open-meteo.com" in url
    assert params["latitude"] == amman.latitude
    assert params["longitude"] == amman.longitude
    assert params["start_date"] == "2025-01-01"
    assert params["end_date"] == "2025-01-31"
    assert "temperature_2m_max" in params["daily"]
    assert params["timezone"] == "Asia/Amman"
    assert payload["daily"]["time"] == ["2025-01-01"]


def test_fetch_air_quality_requests_hourly_pollutants(amman):
    session = FakeSession(FakeResponse({"hourly": {"time": []}}))

    fetch_air_quality(session, amman, START, END)

    url, params = session.calls[0]
    assert "air-quality-api.open-meteo.com" in url
    assert "pm2_5" in params["hourly"]


def test_api_error_body_raises_extract_error(amman):
    session = FakeSession(FakeResponse({"error": True, "reason": "Invalid date"}, status=400))

    with pytest.raises(ExtractError, match="amman"):
        fetch_weather(session, amman, START, END)


def test_error_flag_in_successful_response_raises(amman):
    session = FakeSession(FakeResponse({"error": True, "reason": "quota"}, status=200))

    with pytest.raises(ExtractError, match="quota"):
        fetch_weather(session, amman, START, END)


def test_build_session_retries_on_server_errors_and_rate_limits():
    session = build_session(retries=4)

    retry = session.adapters["https://"].max_retries
    assert retry.total == 4
    assert 429 in retry.status_forcelist
    assert 503 in retry.status_forcelist


def test_save_raw_writes_json_in_a_predictable_place(tmp_path):
    payload = {"daily": {"time": ["2025-01-01"]}}

    path = save_raw(payload, tmp_path, "weather", "amman", START, END)

    assert path == tmp_path / "weather" / "amman" / "2025-01-01_2025-01-31.json"
    assert json.loads(path.read_text(encoding="utf-8")) == payload
