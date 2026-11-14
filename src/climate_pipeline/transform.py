"""Transform raw Open-Meteo JSON payloads into tidy, one-row-per-city-per-day tables."""

from __future__ import annotations

import math

import pandas as pd

from climate_pipeline.config import City

WEATHER_COLUMNS = [
    "city_id",
    "date",
    "temp_max_c",
    "temp_min_c",
    "temp_mean_c",
    "precipitation_mm",
    "wind_speed_max_kmh",
    "humidity_mean_pct",
]

AIR_COLUMNS = [
    "city_id",
    "date",
    "pm2_5_mean",
    "pm2_5_max",
    "pm10_mean",
    "pm10_max",
    "no2_mean",
    "o3_mean",
    "hours_observed",
    "pm2_5_category",
]

_WEATHER_RENAME = {
    "time": "date",
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "temperature_2m_mean": "temp_mean_c",
    "precipitation_sum": "precipitation_mm",
    "wind_speed_10m_max": "wind_speed_max_kmh",
    "relative_humidity_2m_mean": "humidity_mean_pct",
}

# US EPA PM2.5 24-hour AQI breakpoints (2024 revision): (upper bound, category).
_PM25_BREAKPOINTS = (
    (9.0, "Good"),
    (35.4, "Moderate"),
    (55.4, "Unhealthy for Sensitive Groups"),
    (125.4, "Unhealthy"),
    (225.4, "Very Unhealthy"),
)


def pm25_category(value: float) -> str | None:
    """Map a daily mean PM2.5 concentration (µg/m³) to its EPA air-quality category."""
    if value is None or math.isnan(value):
        return None
    rounded = round(value, 1)  # EPA truncates concentrations to one decimal place
    for upper, label in _PM25_BREAKPOINTS:
        if rounded <= upper:
            return label
    return "Hazardous"


def weather_to_frame(payload: dict, city: City) -> pd.DataFrame:
    """Convert an archive-API payload into a daily weather table for one city.

    Raises:
        KeyError: if the payload has no `daily` block (e.g. an API error response).
    """
    if "daily" not in payload:
        raise KeyError("Weather payload has no 'daily' block")
    df = pd.DataFrame(payload["daily"]).rename(columns=_WEATHER_RENAME)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["city_id"] = city.city_id
    numeric = WEATHER_COLUMNS[2:]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce").astype("float64")
    return df[WEATHER_COLUMNS]


def air_quality_to_daily(payload: dict, city: City, min_hours: int = 18) -> pd.DataFrame:
    """Aggregate hourly pollutant readings into daily mean/max values for one city.

    Days with fewer than `min_hours` hourly readings are dropped, because a daily
    average built from a handful of hours is not representative.

    Raises:
        KeyError: if the payload has no `hourly` block.
    """
    if "hourly" not in payload:
        raise KeyError("Air-quality payload has no 'hourly' block")
    hourly = pd.DataFrame(payload["hourly"])
    hourly["date"] = pd.to_datetime(hourly["time"]).dt.date
    pollutants = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone"]
    hourly[pollutants] = hourly[pollutants].apply(pd.to_numeric, errors="coerce")

    daily = hourly.groupby("date", as_index=False).agg(
        pm2_5_mean=("pm2_5", "mean"),
        pm2_5_max=("pm2_5", "max"),
        pm10_mean=("pm10", "mean"),
        pm10_max=("pm10", "max"),
        no2_mean=("nitrogen_dioxide", "mean"),
        o3_mean=("ozone", "mean"),
        hours_observed=("pm2_5", "count"),
    )
    daily = daily[daily["hours_observed"] >= min_hours].reset_index(drop=True)
    value_cols = ["pm2_5_mean", "pm2_5_max", "pm10_mean", "pm10_max", "no2_mean", "o3_mean"]
    daily[value_cols] = daily[value_cols].round(2)
    daily["hours_observed"] = daily["hours_observed"].astype("int64")
    daily["pm2_5_category"] = daily["pm2_5_mean"].map(pm25_category)
    daily["city_id"] = city.city_id
    return daily[AIR_COLUMNS]
