"""Tests for the analytics report built on top of the warehouse."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from climate_pipeline.load import connect, init_schema
from climate_pipeline.pipeline import run_pipeline
from climate_pipeline.report import QUERIES, build_report, run_query, to_markdown
from tests.conftest import make_air_payload, make_weather_payload

DAYS = [(dt.date(2025, 1, 1) + dt.timedelta(d)).isoformat() for d in range(60)]


def weather(city, start, end):
    payload = make_weather_payload(DAYS)
    # Make it rain on the first 10 days so the rainy-vs-dry query has both groups.
    payload["daily"]["precipitation_sum"] = [5.0] * 10 + [0.0] * 50
    return payload


def air(city, start, end):
    pm25 = 40.0 if city.city_id == "aqaba" else 8.0
    return make_air_payload(dict.fromkeys(DAYS, 24), pm25=pm25)


@pytest.fixture
def con(amman, aqaba):
    con = connect(":memory:")
    run_pipeline(con, [amman, aqaba], dt.date(2025, 1, 1), dt.date(2025, 3, 1), weather, air)
    yield con
    con.close()


def test_every_bundled_query_runs(con):
    for name in QUERIES:
        df = run_query(con, name)
        assert not df.empty, f"query {name} returned no rows"


def test_city_summary_ranks_the_most_polluted_city_first(con):
    df = run_query(con, "city_summary")

    assert df.iloc[0]["city"] == "Aqaba"
    assert df.iloc[0]["pct_unhealthy_days"] == pytest.approx(100.0)
    assert df.iloc[1]["pct_unhealthy_days"] == pytest.approx(0.0)


def test_rain_query_compares_rainy_and_dry_days(con):
    df = run_query(con, "rain_vs_air")

    assert set(df["day_type"]) == {"Rainy (>= 1 mm)", "Dry"}


def test_unknown_query_name_is_a_clear_error(con):
    with pytest.raises(KeyError, match="no_such_query"):
        run_query(con, "no_such_query")


def test_build_report_writes_markdown_and_charts(con, tmp_path):
    path = build_report(con, tmp_path)

    text = path.read_text(encoding="utf-8")
    assert path.name == "REPORT.md"
    assert "Aqaba" in text and "Amman" in text
    pngs = sorted(p.name for p in tmp_path.glob("*.png"))
    assert pngs == ["monthly_pm25.png", "pm25_categories.png", "temperature_by_city.png"]


def test_build_report_on_empty_warehouse_fails_clearly(tmp_path):
    empty = connect(":memory:")

    init_schema(empty)

    with pytest.raises(RuntimeError, match="no data"):
        build_report(empty, tmp_path)


def test_markdown_tables_show_dates_without_time():
    df = pd.DataFrame({"date": pd.to_datetime(["2025-01-03"]), "value": [1.5]})

    assert "| 2025-01-03 | 1.5 |" in to_markdown(df)
