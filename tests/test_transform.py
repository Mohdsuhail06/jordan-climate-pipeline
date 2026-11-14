"""Tests for turning raw API payloads into tidy daily tables."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from climate_pipeline.transform import (
    WEATHER_COLUMNS,
    air_quality_to_daily,
    pm25_category,
    weather_to_frame,
)
from tests.conftest import make_air_payload, make_weather_payload


class TestWeatherToFrame:
    def test_one_row_per_day_with_clean_column_names(self, amman):
        payload = make_weather_payload(["2025-01-01", "2025-01-02"])

        df = weather_to_frame(payload, amman)

        assert list(df.columns) == WEATHER_COLUMNS
        assert len(df) == 2
        assert (df["city_id"] == "amman").all()
        assert df["date"].tolist() == [dt.date(2025, 1, 1), dt.date(2025, 1, 2)]
        assert df["temp_max_c"].tolist() == [20.0, 21.0]

    def test_missing_values_stay_missing(self, amman):
        payload = make_weather_payload(["2025-01-01", "2025-01-02"], t_max=[None, 18.0])

        df = weather_to_frame(payload, amman)

        assert pd.isna(df.loc[0, "temp_max_c"])
        assert df.loc[1, "temp_max_c"] == 18.0

    def test_payload_without_daily_block_raises(self, amman):
        with pytest.raises(KeyError, match="daily"):
            weather_to_frame({"error": True}, amman)


class TestAirQualityToDaily:
    def test_hourly_readings_are_averaged_per_day(self, amman):
        payload = make_air_payload({"2025-01-01": 24, "2025-01-02": 24}, pm25=12.0)

        df = air_quality_to_daily(payload, amman)

        assert len(df) == 2
        assert df["pm2_5_mean"].tolist() == [12.0, 12.0]
        assert df["pm10_mean"].tolist() == [24.0, 24.0]
        assert df["hours_observed"].tolist() == [24, 24]

    def test_daily_max_is_the_highest_hour(self, amman):
        payload = make_air_payload({"2025-01-01": 24}, pm25=5.0)
        payload["hourly"]["pm2_5"][13] = 80.0

        df = air_quality_to_daily(payload, amman)

        assert df.loc[0, "pm2_5_max"] == 80.0

    def test_days_with_too_few_hours_are_dropped(self, amman):
        # 2025-01-02 only has 10 hours of data: not enough to trust a daily mean.
        payload = make_air_payload({"2025-01-01": 24, "2025-01-02": 10})

        df = air_quality_to_daily(payload, amman, min_hours=18)

        assert df["date"].tolist() == [dt.date(2025, 1, 1)]

    def test_category_column_is_added(self, amman):
        payload = make_air_payload({"2025-01-01": 24}, pm25=40.0)

        df = air_quality_to_daily(payload, amman)

        assert df.loc[0, "pm2_5_category"] == "Unhealthy for Sensitive Groups"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "Good"),
        (9.0, "Good"),
        (9.1, "Moderate"),
        (35.4, "Moderate"),
        (35.5, "Unhealthy for Sensitive Groups"),
        (55.5, "Unhealthy"),
        (125.5, "Very Unhealthy"),
        (300.0, "Hazardous"),
    ],
)
def test_pm25_category_uses_epa_2024_breakpoints(value, expected):
    assert pm25_category(value) == expected


def test_pm25_category_of_missing_value_is_none():
    assert pm25_category(float("nan")) is None
