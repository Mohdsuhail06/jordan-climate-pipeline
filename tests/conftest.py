"""Shared test fixtures: small, hand-built API payloads (no network needed)."""

from __future__ import annotations

import pytest

from climate_pipeline.config import City

AMMAN = City(city_id="amman", name="Amman", governorate="Amman", latitude=31.95, longitude=35.93)
AQABA = City(city_id="aqaba", name="Aqaba", governorate="Aqaba", latitude=29.53, longitude=35.01)


def make_weather_payload(dates: list[str], t_max: list[float | None] | None = None) -> dict:
    """Build a payload shaped like the Open-Meteo archive API `daily` response."""
    n = len(dates)
    return {
        "latitude": 31.95,
        "longitude": 35.89,
        "timezone": "Asia/Amman",
        "daily": {
            "time": dates,
            "temperature_2m_max": t_max if t_max is not None else [20.0 + i for i in range(n)],
            "temperature_2m_min": [10.0 + i for i in range(n)],
            "temperature_2m_mean": [15.0 + i for i in range(n)],
            "precipitation_sum": [0.0] * n,
            "wind_speed_10m_max": [12.5] * n,
            "relative_humidity_2m_mean": [55] * n,
        },
    }


def make_air_payload(day_hours: dict[str, int], pm25: float = 10.0) -> dict:
    """Build an hourly air-quality payload.

    `day_hours` maps a date to how many hourly readings it has (24 = complete day).
    """
    times: list[str] = []
    for day, hours in day_hours.items():
        times += [f"{day}T{h:02d}:00" for h in range(hours)]
    n = len(times)
    return {
        "latitude": 32.0,
        "longitude": 35.9,
        "timezone": "Asia/Amman",
        "hourly": {
            "time": times,
            "pm2_5": [pm25] * n,
            "pm10": [pm25 * 2] * n,
            "nitrogen_dioxide": [20.0] * n,
            "ozone": [60.0] * n,
        },
    }


@pytest.fixture
def amman() -> City:
    return AMMAN


@pytest.fixture
def aqaba() -> City:
    return AQABA
