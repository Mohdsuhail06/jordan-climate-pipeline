"""Tests for the command-line interface. The real API fetchers are replaced with fakes."""

from __future__ import annotations

import datetime as dt

import pytest

from climate_pipeline import cli
from climate_pipeline.extract import ExtractError
from tests.conftest import make_air_payload, make_weather_payload


def fake_weather(session, city, start, end):
    days = [(start + dt.timedelta(d)).isoformat() for d in range((end - start).days + 1)]
    return make_weather_payload(days)


def fake_air(session, city, start, end):
    days = [(start + dt.timedelta(d)).isoformat() for d in range((end - start).days + 1)]
    return make_air_payload(dict.fromkeys(days, 24))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(cli, "fetch_weather", fake_weather)
    monkeypatch.setattr(cli, "fetch_air_quality", fake_air)


def test_run_command_loads_data_and_saves_raw_files(tmp_path, capsys):
    db = tmp_path / "w.duckdb"
    raw = tmp_path / "raw"

    code = cli.main(
        [
            "run",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-05",
            "--cities",
            "amman",
            "--db",
            str(db),
            "--raw-dir",
            str(raw),
        ]
    )

    assert code == 0
    assert db.exists()
    assert (raw / "weather" / "amman" / "2025-01-01_2025-01-05.json").exists()
    assert "success" in capsys.readouterr().out


def test_report_command_writes_report(tmp_path):
    db = tmp_path / "w.duckdb"
    cli.main(
        [
            "run",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-31",
            "--db",
            str(db),
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )

    code = cli.main(["report", "--db", str(db), "--out", str(tmp_path / "rep")])

    assert code == 0
    assert (tmp_path / "rep" / "REPORT.md").exists()


def test_unknown_city_exits_with_error(tmp_path, capsys):
    code = cli.main(
        [
            "run",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-02",
            "--cities",
            "paris",
            "--db",
            str(tmp_path / "w.duckdb"),
        ]
    )

    assert code == 2
    assert "Unknown city" in capsys.readouterr().err


def test_bad_date_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        cli.main(["run", "--start", "01/01/2025", "--end", "2025-01-02"])


def test_report_without_database_exits_with_error(tmp_path, capsys):
    code = cli.main(["report", "--db", str(tmp_path / "missing.duckdb")])

    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_failed_run_returns_non_zero(tmp_path, monkeypatch):

    def broken(session, city, start, end):
        raise ExtractError("down")

    monkeypatch.setattr(cli, "fetch_weather", broken)
    monkeypatch.setattr(cli, "fetch_air_quality", broken)

    code = cli.main(
        [
            "run",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-02",
            "--cities",
            "amman",
            "--db",
            str(tmp_path / "w.duckdb"),
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )

    assert code == 1
