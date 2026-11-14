"""End-to-end tests of the whole ETL run, with fake data sources instead of the real API."""

from __future__ import annotations

import datetime as dt

import pytest

from climate_pipeline.extract import ExtractError
from climate_pipeline.load import connect
from climate_pipeline.pipeline import date_chunks, run_pipeline
from tests.conftest import make_air_payload, make_weather_payload

START, END = dt.date(2025, 1, 1), dt.date(2025, 1, 3)
DAYS = ["2025-01-01", "2025-01-02", "2025-01-03"]


def good_weather(city, start, end):
    return make_weather_payload(DAYS)


def good_air(city, start, end):
    return make_air_payload(dict.fromkeys(DAYS, 24))


@pytest.fixture
def con():
    con = connect(":memory:")
    yield con
    con.close()


def count(con, table):
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_full_run_loads_every_city_and_day(con, amman, aqaba):
    summary = run_pipeline(con, [amman, aqaba], START, END, good_weather, good_air)

    assert summary.status == "success"
    assert summary.weather_rows == 6
    assert summary.air_rows == 6
    assert summary.rejected_rows == 0
    assert count(con, "fact_weather_daily") == 6
    assert count(con, "fact_air_quality_daily") == 6


def test_running_twice_gives_the_same_result(con, amman):
    run_pipeline(con, [amman], START, END, good_weather, good_air)
    run_pipeline(con, [amman], START, END, good_weather, good_air)

    assert count(con, "fact_weather_daily") == 3
    assert count(con, "pipeline_runs") == 2


def test_bad_rows_are_quarantined_not_loaded(con, amman):
    def weather_with_bad_day(city, start, end):
        payload = make_weather_payload(DAYS)
        payload["daily"]["precipitation_sum"][1] = -4.0
        return payload

    summary = run_pipeline(con, [amman], START, END, weather_with_bad_day, good_air)

    assert summary.weather_rows == 2
    assert summary.rejected_rows == 1
    assert count(con, "quarantine") == 1


def test_one_failing_city_does_not_stop_the_others(con, amman, aqaba):
    def flaky_weather(city, start, end):
        if city.city_id == "aqaba":
            raise ExtractError("aqaba: server unavailable")
        return good_weather(city, start, end)

    summary = run_pipeline(con, [amman, aqaba], START, END, flaky_weather, good_air)

    assert summary.status == "partial"
    assert summary.failed == ["weather:aqaba"]
    assert summary.weather_rows == 3
    status = con.execute("SELECT status, message FROM pipeline_runs").fetchone()
    assert status[0] == "partial"
    assert "aqaba" in status[1]


def test_all_sources_failing_marks_run_as_failed(con, amman):
    def broken(city, start, end):
        raise ExtractError("down")

    summary = run_pipeline(con, [amman], START, END, broken, broken)

    assert summary.status == "failed"


def test_start_after_end_is_rejected(con, amman):
    with pytest.raises(ValueError, match="start"):
        run_pipeline(con, [amman], END, START, good_weather, good_air)


def test_long_ranges_are_fetched_in_chunks(con, amman):
    seen = []

    def recording_weather(city, start, end):
        seen.append((start, end))
        days = [(start + dt.timedelta(d)).isoformat() for d in range((end - start).days + 1)]
        return make_weather_payload(days)

    summary = run_pipeline(
        con,
        [amman],
        dt.date(2025, 1, 1),
        dt.date(2025, 3, 1),
        recording_weather,
        good_air,
        chunk_days=31,
    )

    assert seen == [
        (dt.date(2025, 1, 1), dt.date(2025, 1, 31)),
        (dt.date(2025, 2, 1), dt.date(2025, 3, 1)),
    ]
    assert summary.weather_rows == 60


def test_date_chunks_cover_the_range_without_gaps():
    chunks = date_chunks(dt.date(2025, 1, 1), dt.date(2025, 1, 10), size=4)

    assert chunks == [
        (dt.date(2025, 1, 1), dt.date(2025, 1, 4)),
        (dt.date(2025, 1, 5), dt.date(2025, 1, 8)),
        (dt.date(2025, 1, 9), dt.date(2025, 1, 10)),
    ]
