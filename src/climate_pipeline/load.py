"""Load step: a small star-schema warehouse in DuckDB, with idempotent upserts and run auditing."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd

from climate_pipeline.config import City
from climate_pipeline.transform import AIR_COLUMNS, WEATHER_COLUMNS
from climate_pipeline.validate import QUARANTINE_COLUMNS

SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS run_id_seq START 1;

CREATE TABLE IF NOT EXISTS dim_city (
    city_id     VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    governorate VARCHAR NOT NULL,
    latitude    DOUBLE  NOT NULL,
    longitude   DOUBLE  NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_date (
    date        DATE PRIMARY KEY,
    year        INTEGER NOT NULL,
    month       INTEGER NOT NULL,
    day_of_week VARCHAR NOT NULL,
    is_weekend  BOOLEAN NOT NULL,
    season      VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_weather_daily (
    city_id            VARCHAR NOT NULL REFERENCES dim_city (city_id),
    date               DATE    NOT NULL REFERENCES dim_date (date),
    temp_max_c         DOUBLE,
    temp_min_c         DOUBLE,
    temp_mean_c        DOUBLE,
    precipitation_mm   DOUBLE,
    wind_speed_max_kmh DOUBLE,
    humidity_mean_pct  DOUBLE,
    loaded_at          TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (city_id, date)
);

CREATE TABLE IF NOT EXISTS fact_air_quality_daily (
    city_id        VARCHAR NOT NULL REFERENCES dim_city (city_id),
    date           DATE    NOT NULL REFERENCES dim_date (date),
    pm2_5_mean     DOUBLE,
    pm2_5_max      DOUBLE,
    pm10_mean      DOUBLE,
    pm10_max       DOUBLE,
    no2_mean       DOUBLE,
    o3_mean        DOUBLE,
    hours_observed INTEGER,
    pm2_5_category VARCHAR,
    loaded_at      TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (city_id, date)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id        INTEGER PRIMARY KEY,
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    status        VARCHAR NOT NULL,
    rows_loaded   INTEGER,
    rows_rejected INTEGER,
    message       VARCHAR
);

CREATE TABLE IF NOT EXISTS quarantine (
    run_id   INTEGER NOT NULL,
    dataset  VARCHAR NOT NULL,
    city_id  VARCHAR,
    date     DATE,
    reason   VARCHAR NOT NULL,
    record   VARCHAR,
    added_at TIMESTAMP DEFAULT current_timestamp
);
"""

_SEASONS = {
    12: "Winter",
    1: "Winter",
    2: "Winter",
    3: "Spring",
    4: "Spring",
    5: "Spring",
    6: "Summer",
    7: "Summer",
    8: "Summer",
    9: "Autumn",
    10: "Autumn",
    11: "Autumn",
}


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (or create) the warehouse. Use ":memory:" for a throw-away database."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables if they do not exist yet (safe to call on every run)."""
    con.execute(SCHEMA_SQL)


def upsert_cities(con: duckdb.DuckDBPyConnection, cities: Iterable[City]) -> None:
    """Insert or refresh the city dimension."""
    rows = [(c.city_id, c.name, c.governorate, c.latitude, c.longitude) for c in cities]
    con.executemany("INSERT OR REPLACE INTO dim_city VALUES (?, ?, ?, ?, ?)", rows)


def _upsert_dates(con: duckdb.DuckDBPyConnection, dates: Iterable[dt.date]) -> None:
    rows = [
        (d, d.year, d.month, d.strftime("%A"), d.weekday() in (4, 5), _SEASONS[d.month])
        for d in sorted(set(dates))
    ]
    if rows:
        con.executemany("INSERT OR IGNORE INTO dim_date VALUES (?, ?, ?, ?, ?, ?)", rows)


def _upsert_fact(
    con: duckdb.DuckDBPyConnection, df: pd.DataFrame, table: str, columns: list[str]
) -> int:
    if df.empty:
        return 0
    _upsert_dates(con, df["date"])
    con.register("incoming", df[columns])
    try:
        col_list = ", ".join(columns)
        con.execute(f"INSERT OR REPLACE INTO {table} ({col_list}) SELECT {col_list} FROM incoming")
    finally:
        con.unregister("incoming")
    return len(df)


def upsert_weather(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Insert daily weather rows; a row for an existing (city, date) replaces the old one."""
    return _upsert_fact(con, df, "fact_weather_daily", WEATHER_COLUMNS)


def upsert_air_quality(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Insert daily air-quality rows; a row for an existing (city, date) replaces the old one."""
    return _upsert_fact(con, df, "fact_air_quality_daily", AIR_COLUMNS)


def insert_quarantine(con: duckdb.DuckDBPyConnection, rejected: pd.DataFrame, run_id: int) -> int:
    """Store rows that failed validation, together with the reason, for later inspection."""
    if rejected.empty:
        return 0
    frame = rejected[QUARANTINE_COLUMNS].copy()
    frame.insert(0, "run_id", run_id)
    con.register("rejected_rows", frame)
    try:
        con.execute(
            "INSERT INTO quarantine (run_id, dataset, city_id, date, reason, record) "
            "SELECT run_id, dataset, city_id, date, reason, record FROM rejected_rows"
        )
    finally:
        con.unregister("rejected_rows")
    return len(frame)


def start_run(con: duckdb.DuckDBPyConnection, start: dt.date, end: dt.date) -> int:
    """Record the start of a pipeline run and return its id."""
    run_id = con.execute("SELECT nextval('run_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO pipeline_runs (run_id, start_date, end_date, started_at, status) "
        "VALUES (?, ?, ?, current_timestamp, 'running')",
        [run_id, start, end],
    )
    return int(run_id)


def finish_run(
    con: duckdb.DuckDBPyConnection,
    run_id: int,
    status: str,
    rows_loaded: int,
    rows_rejected: int,
    message: str = "",
) -> None:
    """Mark a run as finished with its final status and row counts."""
    con.execute(
        "UPDATE pipeline_runs SET finished_at = current_timestamp, status = ?, rows_loaded = ?, "
        "rows_rejected = ?, message = ? WHERE run_id = ?",
        [status, rows_loaded, rows_rejected, message, run_id],
    )
