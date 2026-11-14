"""Tests for loading into the DuckDB warehouse (uses an in-memory database)."""

from __future__ import annotations

import datetime as dt

import pytest

from climate_pipeline.load import (
    connect,
    finish_run,
    init_schema,
    insert_quarantine,
    start_run,
    upsert_air_quality,
    upsert_cities,
    upsert_weather,
)
from climate_pipeline.transform import air_quality_to_daily, weather_to_frame
from climate_pipeline.validate import validate_weather
from tests.conftest import make_air_payload, make_weather_payload


@pytest.fixture
def con(amman, aqaba):
    con = connect(":memory:")
    init_schema(con)
    upsert_cities(con, [amman, aqaba])
    yield con
    con.close()


def count(con, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_schema_creates_all_tables(con):
    tables = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }

    assert {
        "dim_city",
        "dim_date",
        "fact_weather_daily",
        "fact_air_quality_daily",
        "quarantine",
        "pipeline_runs",
    } <= tables


def test_init_schema_can_run_twice(con):
    init_schema(con)  # must not fail or wipe data
    assert count(con, "dim_city") == 2


def test_weather_rows_are_loaded(con, amman):
    df = weather_to_frame(make_weather_payload(["2025-01-01", "2025-01-02"]), amman)

    loaded = upsert_weather(con, df)

    assert loaded == 2
    assert count(con, "fact_weather_daily") == 2


def test_loading_the_same_days_twice_does_not_duplicate(con, amman):
    df = weather_to_frame(make_weather_payload(["2025-01-01", "2025-01-02"]), amman)

    upsert_weather(con, df)
    upsert_weather(con, df)

    assert count(con, "fact_weather_daily") == 2


def test_reloading_a_day_updates_its_values(con, amman):
    upsert_weather(con, weather_to_frame(make_weather_payload(["2025-01-01"]), amman))
    corrected = weather_to_frame(make_weather_payload(["2025-01-01"], t_max=[33.3]), amman)

    upsert_weather(con, corrected)

    value = con.execute("SELECT temp_max_c FROM fact_weather_daily").fetchone()[0]
    assert value == pytest.approx(33.3)


def test_date_dimension_is_filled_with_calendar_attributes(con, amman):
    upsert_weather(con, weather_to_frame(make_weather_payload(["2025-01-03"]), amman))

    row = con.execute(
        "SELECT year, month, day_of_week, is_weekend, season "
        "FROM dim_date WHERE date = '2025-01-03'"
    ).fetchone()
    # 2025-01-03 is a Friday, which is part of the weekend in Jordan (Fri-Sat).
    assert row == (2025, 1, "Friday", True, "Winter")


def test_air_quality_rows_are_loaded(con, amman):
    df = air_quality_to_daily(make_air_payload({"2025-01-01": 24}), amman)

    assert upsert_air_quality(con, df) == 1
    category = con.execute("SELECT pm2_5_category FROM fact_air_quality_daily").fetchone()[0]
    assert category == "Moderate"  # default PM2.5 of 10 is above the 9.0 "Good" limit


def test_empty_frame_loads_nothing(con, amman):
    df = weather_to_frame(make_weather_payload([]), amman)

    assert upsert_weather(con, df) == 0


def test_quarantine_rows_are_stored_with_run_id(con, amman):
    df = weather_to_frame(make_weather_payload(["2025-01-01"]), amman)
    df.loc[0, "precipitation_mm"] = -5
    rejected = validate_weather(df).rejected
    run_id = start_run(con, dt.date(2025, 1, 1), dt.date(2025, 1, 1))

    insert_quarantine(con, rejected, run_id)

    row = con.execute("SELECT run_id, dataset, reason FROM quarantine").fetchone()
    assert row == (run_id, "weather", "precipitation_mm < 0")


def test_pipeline_run_is_audited(con):
    run_id = start_run(con, dt.date(2025, 1, 1), dt.date(2025, 1, 31))

    finish_run(con, run_id, status="success", rows_loaded=10, rows_rejected=1, message="ok")

    row = con.execute(
        "SELECT status, rows_loaded, rows_rejected, finished_at IS NOT NULL FROM pipeline_runs"
    ).fetchone()
    assert row == ("success", 10, 1, True)


def test_connect_creates_missing_parent_folder(tmp_path):
    db = tmp_path / "nested" / "dir" / "w.duckdb"

    con = connect(db)
    con.close()

    assert db.exists()
