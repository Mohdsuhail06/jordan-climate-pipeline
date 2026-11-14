"""Tests for data-quality checks: bad rows go to quarantine, good rows pass."""

from __future__ import annotations

import pandas as pd

from climate_pipeline.transform import air_quality_to_daily, weather_to_frame
from climate_pipeline.validate import validate_air_quality, validate_weather
from tests.conftest import make_air_payload, make_weather_payload


def _weather(amman, n=3):
    dates = [f"2025-01-0{i + 1}" for i in range(n)]
    return weather_to_frame(make_weather_payload(dates), amman)


class TestValidateWeather:
    def test_clean_data_passes_untouched(self, amman):
        df = _weather(amman)

        result = validate_weather(df)

        assert len(result.valid) == 3
        assert result.rejected.empty

    def test_min_above_max_is_rejected_with_reason(self, amman):
        df = _weather(amman)
        df.loc[1, "temp_min_c"] = 50.0

        result = validate_weather(df)

        assert len(result.valid) == 2
        assert len(result.rejected) == 1
        assert "temp_min_c > temp_max_c" in result.rejected.iloc[0]["reason"]

    def test_negative_precipitation_is_rejected(self, amman):
        df = _weather(amman)
        df.loc[0, "precipitation_mm"] = -1.0

        result = validate_weather(df)

        assert "precipitation_mm < 0" in result.rejected.iloc[0]["reason"]

    def test_humidity_out_of_range_is_rejected(self, amman):
        df = _weather(amman)
        df.loc[2, "humidity_mean_pct"] = 140

        result = validate_weather(df)

        assert "humidity_mean_pct out of 0-100" in result.rejected.iloc[0]["reason"]

    def test_missing_temperature_is_rejected(self, amman):
        df = _weather(amman)
        df.loc[0, "temp_mean_c"] = None

        result = validate_weather(df)

        assert "temp_mean_c is null" in result.rejected.iloc[0]["reason"]

    def test_duplicate_city_and_date_keeps_only_first(self, amman):
        df = _weather(amman)
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)

        result = validate_weather(df)

        assert len(result.valid) == 3
        assert "duplicate" in result.rejected.iloc[0]["reason"]

    def test_row_with_two_problems_lists_both(self, amman):
        df = _weather(amman)
        df.loc[0, "precipitation_mm"] = -2.0
        df.loc[0, "humidity_mean_pct"] = -5

        result = validate_weather(df)

        reason = result.rejected.iloc[0]["reason"]
        assert "precipitation_mm < 0" in reason
        assert "humidity_mean_pct out of 0-100" in reason

    def test_rejected_rows_keep_their_original_data_as_json(self, amman):
        df = _weather(amman)
        df.loc[0, "precipitation_mm"] = -1.0

        result = validate_weather(df)

        assert '"precipitation_mm": -1.0' in result.rejected.iloc[0]["record"]
        assert result.rejected.iloc[0]["dataset"] == "weather"


class TestValidateAirQuality:
    def test_clean_data_passes(self, amman):
        df = air_quality_to_daily(make_air_payload({"2025-01-01": 24}), amman)

        result = validate_air_quality(df)

        assert len(result.valid) == 1
        assert result.rejected.empty

    def test_negative_concentration_is_rejected(self, amman):
        df = air_quality_to_daily(make_air_payload({"2025-01-01": 24}), amman)
        df.loc[0, "no2_mean"] = -3.0

        result = validate_air_quality(df)

        assert result.valid.empty
        assert "no2_mean < 0" in result.rejected.iloc[0]["reason"]

    def test_pm25_larger_than_pm10_is_rejected(self, amman):
        # PM2.5 particles are a subset of PM10, so PM2.5 can never exceed PM10.
        df = air_quality_to_daily(make_air_payload({"2025-01-01": 24}), amman)
        df.loc[0, "pm2_5_mean"] = 99.0

        result = validate_air_quality(df)

        assert "pm2_5_mean > pm10_mean" in result.rejected.iloc[0]["reason"]


def test_null_precipitation_is_rejected(amman):
    df = _weather(amman)
    df.loc[0, "precipitation_mm"] = None

    result = validate_weather(df)

    assert "precipitation_mm is null" in result.rejected.iloc[0]["reason"]


def test_valid_duplicate_is_kept_when_the_first_copy_is_invalid(amman):
    df = _weather(amman)
    bad_copy = df.iloc[[0]].copy()
    bad_copy["precipitation_mm"] = -1.0
    df = pd.concat([bad_copy, df], ignore_index=True)  # invalid copy comes first

    result = validate_weather(df)

    assert len(result.valid) == 3
    assert result.rejected.iloc[0]["reason"] == "precipitation_mm < 0"


def test_air_quality_day_with_too_few_hours_is_rejected(amman):
    df = air_quality_to_daily(make_air_payload({"2025-01-01": 24, "2025-01-02": 10}), amman)

    result = validate_air_quality(df)

    assert len(result.valid) == 1
    assert "hours_observed < 18" in result.rejected.iloc[0]["reason"]
