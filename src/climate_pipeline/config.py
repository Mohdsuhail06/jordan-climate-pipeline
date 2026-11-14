"""Static configuration: which cities we track, which API fields we request, where files live."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WEATHER_API_URL = "https://archive-api.open-meteo.com/v1/archive"
AIR_QUALITY_API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEZONE = "Asia/Amman"

# Daily weather variables requested from the Open-Meteo historical (archive) API.
DAILY_WEATHER_VARS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
    "relative_humidity_2m_mean",
)

# Hourly pollutant variables requested from the Open-Meteo air-quality API (CAMS model).
HOURLY_AIR_VARS = ("pm2_5", "pm10", "nitrogen_dioxide", "ozone")

DEFAULT_DB_PATH = Path("data/warehouse.duckdb")
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_REPORT_DIR = Path("reports")


@dataclass(frozen=True)
class City:
    """A location we collect data for."""

    city_id: str
    name: str
    governorate: str
    latitude: float
    longitude: float


CITIES: tuple[City, ...] = (
    City("amman", "Amman", "Amman", 31.9539, 35.9106),
    City("zarqa", "Zarqa", "Zarqa", 32.0728, 36.0880),
    City("irbid", "Irbid", "Irbid", 32.5556, 35.8500),
    City("aqaba", "Aqaba", "Aqaba", 29.5320, 35.0063),
    City("madaba", "Madaba", "Madaba", 31.7160, 35.7939),
    City("karak", "Al-Karak", "Karak", 31.1853, 35.7048),
    City("mafraq", "Mafraq", "Mafraq", 32.3434, 36.2080),
    City("maan", "Ma'an", "Ma'an", 30.1962, 35.7341),
)


def get_cities(ids: list[str] | None = None) -> tuple[City, ...]:
    """Return all cities, or only those whose `city_id` is in `ids`.

    Raises:
        ValueError: if an unknown city id is requested.
    """
    if not ids:
        return CITIES
    by_id = {c.city_id: c for c in CITIES}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise ValueError(f"Unknown city id(s): {', '.join(unknown)}. Known: {', '.join(by_id)}")
    return tuple(by_id[i] for i in ids)
