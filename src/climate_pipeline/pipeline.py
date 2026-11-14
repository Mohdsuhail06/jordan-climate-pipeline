"""Orchestration: extract -> transform -> validate -> load, for every city and date chunk."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from climate_pipeline.config import City
from climate_pipeline.extract import ExtractError
from climate_pipeline.load import (
    finish_run,
    init_schema,
    insert_quarantine,
    start_run,
    upsert_air_quality,
    upsert_cities,
    upsert_weather,
)
from climate_pipeline.transform import air_quality_to_daily, weather_to_frame
from climate_pipeline.validate import ValidationResult, validate_air_quality, validate_weather

log = logging.getLogger(__name__)

# A fetcher downloads one source for one city and date range and returns the raw JSON.
Fetcher = Callable[[City, dt.date, dt.date], dict]


@dataclass
class RunSummary:
    """What happened during one pipeline run."""

    run_id: int
    status: str = "success"
    weather_rows: int = 0
    air_rows: int = 0
    rejected_rows: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def rows_loaded(self) -> int:
        return self.weather_rows + self.air_rows


def date_chunks(start: dt.date, end: dt.date, size: int) -> list[tuple[dt.date, dt.date]]:
    """Split [start, end] into consecutive, non-overlapping ranges of at most `size` days."""
    if size < 1:
        raise ValueError(f"chunk size must be at least 1 day, got {size}")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + dt.timedelta(days=size - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + dt.timedelta(days=1)
    return chunks


def _process(
    name: str,
    fetch: Fetcher,
    to_frame: Callable[[dict, City], pd.DataFrame],
    validate: Callable[[pd.DataFrame], ValidationResult],
    upsert: Callable[[duckdb.DuckDBPyConnection, pd.DataFrame], int],
    con: duckdb.DuckDBPyConnection,
    city: City,
    chunks: list[tuple[dt.date, dt.date]],
    summary: RunSummary,
) -> int:
    """Run one source for one city. Returns rows loaded; records failures on the summary."""
    loaded = 0
    for chunk_start, chunk_end in chunks:
        try:
            frame = to_frame(fetch(city, chunk_start, chunk_end), city)
        except (ExtractError, KeyError) as exc:
            log.error("%s failed for %s: %s", name, city.city_id, exc)
            summary.failed.append(f"{name}:{city.city_id}")
            return loaded
        result = validate(frame)
        loaded += upsert(con, result.valid)
        summary.rejected_rows += insert_quarantine(con, result.rejected, summary.run_id)
    return loaded


def run_pipeline(
    con: duckdb.DuckDBPyConnection,
    cities: Sequence[City],
    start: dt.date,
    end: dt.date,
    fetch_weather: Fetcher,
    fetch_air: Fetcher,
    chunk_days: int = 366,
) -> RunSummary:
    """Run the full ETL for the given cities and date range.

    A failure for one city/source is logged and recorded, and the run continues
    with the rest (status "partial"). If nothing could be extracted the status is "failed".
    """
    if start > end:
        raise ValueError(f"start ({start}) must be on or before end ({end})")

    init_schema(con)
    upsert_cities(con, cities)
    chunks = date_chunks(start, end, chunk_days)
    summary = RunSummary(run_id=start_run(con, start, end))
    try:
        _run_all_cities(con, cities, chunks, fetch_weather, fetch_air, summary)
    except Exception as exc:
        # Never leave a run stuck at "running": record the crash, then re-raise it.
        summary.status = "failed"
        finish_run(
            con,
            summary.run_id,
            "failed",
            summary.rows_loaded,
            summary.rejected_rows,
            f"crashed: {exc!r}"[:500],
        )
        raise

    total_jobs = 2 * len(cities)
    if len(summary.failed) == total_jobs:
        summary.status = "failed"
    elif summary.failed:
        summary.status = "partial"

    message = f"failed: {', '.join(summary.failed)}" if summary.failed else "ok"
    finish_run(
        con, summary.run_id, summary.status, summary.rows_loaded, summary.rejected_rows, message
    )
    log.info("Run %s finished: %s", summary.run_id, summary)
    return summary


def _run_all_cities(
    con: duckdb.DuckDBPyConnection,
    cities: Sequence[City],
    chunks: list[tuple[dt.date, dt.date]],
    fetch_weather: Fetcher,
    fetch_air: Fetcher,
    summary: RunSummary,
) -> None:
    for city in cities:
        summary.weather_rows += _process(
            "weather",
            fetch_weather,
            weather_to_frame,
            validate_weather,
            upsert_weather,
            con,
            city,
            chunks,
            summary,
        )
        summary.air_rows += _process(
            "air",
            fetch_air,
            air_quality_to_daily,
            validate_air_quality,
            upsert_air_quality,
            con,
            city,
            chunks,
            summary,
        )
