"""Command-line interface.

Examples:
    climate-pipeline run --start 2023-01-01 --end 2025-12-31
    climate-pipeline run --start 2025-01-01 --end 2025-01-31 --cities amman irbid
    climate-pipeline report
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from functools import partial
from pathlib import Path

from climate_pipeline.config import (
    DEFAULT_DB_PATH,
    DEFAULT_RAW_DIR,
    DEFAULT_REPORT_DIR,
    City,
    get_cities,
)
from climate_pipeline.extract import build_session, fetch_air_quality, fetch_weather, save_raw
from climate_pipeline.load import connect
from climate_pipeline.pipeline import run_pipeline
from climate_pipeline.report import build_report


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' is not a date in YYYY-MM-DD format") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="climate-pipeline",
        description="ETL pipeline for daily weather and air quality in Jordanian cities.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="extract, validate and load data for a date range")
    run.add_argument("--start", type=_date, default=dt.date(2023, 1, 1), help="YYYY-MM-DD")
    run.add_argument("--end", type=_date, default=dt.date(2025, 12, 31), help="YYYY-MM-DD")
    run.add_argument("--cities", nargs="+", help="city ids (default: all)")
    run.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="DuckDB file")
    run.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="raw JSON folder")

    report = sub.add_parser("report", help="build the analytics report from the warehouse")
    report.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="DuckDB file")
    report.add_argument("--out", type=Path, default=DEFAULT_REPORT_DIR, help="output folder")
    return parser


def _archiving(fetch, session, raw_dir: Path, source: str):
    """Wrap a fetcher so every raw response is also saved to disk."""

    def wrapped(city: City, start: dt.date, end: dt.date) -> dict:
        payload = fetch(session, city, start, end)
        save_raw(payload, raw_dir, source, city.city_id, start, end)
        return payload

    return wrapped


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        cities = get_cities(args.cities)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    session = build_session()
    weather = _archiving(partial(fetch_weather), session, args.raw_dir, "weather")
    air = _archiving(partial(fetch_air_quality), session, args.raw_dir, "air_quality")

    con = connect(args.db)
    try:
        summary = run_pipeline(con, cities, args.start, args.end, weather, air)
    finally:
        con.close()

    print(
        f"Run {summary.run_id}: {summary.status} | weather rows {summary.weather_rows:,} | "
        f"air rows {summary.air_rows:,} | quarantined {summary.rejected_rows:,}"
    )
    if summary.failed:
        print(f"Failed sources: {', '.join(summary.failed)}")
    return 1 if summary.status == "failed" else 0


def _cmd_report(args: argparse.Namespace) -> int:
    if not args.db.exists():
        print(
            f"error: database {args.db} not found. Run 'climate-pipeline run' first.",
            file=sys.stderr,
        )
        return 2
    con = connect(args.db)
    try:
        path = build_report(con, args.out)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        con.close()
    print(f"Report written to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 = success)."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    if args.command == "run":
        return _cmd_run(args)
    return _cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
