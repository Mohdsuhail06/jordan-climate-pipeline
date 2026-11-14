"""Data-quality rules. Rows that break a rule are quarantined (kept with a reason), not lost."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

QUARANTINE_COLUMNS = ["dataset", "city_id", "date", "reason", "record"]

# A rule takes the table and returns a boolean Series: True where the row is BAD.
Rule = tuple[str, Callable[[pd.DataFrame], pd.Series]]


@dataclass
class ValidationResult:
    """Output of a validation step."""

    valid: pd.DataFrame
    rejected: pd.DataFrame


def _not_null(col: str) -> Rule:
    return (f"{col} is null", lambda df: df[col].isna())


def _non_negative(col: str) -> Rule:
    return (f"{col} < 0", lambda df: df[col] < 0)


WEATHER_RULES: list[Rule] = [
    _not_null("temp_max_c"),
    _not_null("temp_min_c"),
    _not_null("temp_mean_c"),
    ("temp_min_c > temp_max_c", lambda df: df["temp_min_c"] > df["temp_max_c"]),
    (
        "temperature out of -30..60 C",
        lambda df: (df["temp_max_c"] > 60) | (df["temp_min_c"] < -30),
    ),
    _non_negative("precipitation_mm"),
    _non_negative("wind_speed_max_kmh"),
    (
        "humidity_mean_pct out of 0-100",
        lambda df: (df["humidity_mean_pct"] < 0) | (df["humidity_mean_pct"] > 100),
    ),
]

AIR_RULES: list[Rule] = [
    _not_null("pm2_5_mean"),
    _not_null("pm10_mean"),
    _non_negative("pm2_5_mean"),
    _non_negative("pm10_mean"),
    _non_negative("no2_mean"),
    _non_negative("o3_mean"),
    ("pm2_5_mean > pm10_mean", lambda df: df["pm2_5_mean"] > df["pm10_mean"]),
]


def _to_json(row: pd.Series) -> str:
    """Serialise a row so the original values survive in the quarantine table."""
    clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
    return json.dumps(clean, default=str)


def _apply_rules(df: pd.DataFrame, rules: list[Rule], dataset: str) -> ValidationResult:
    df = df.reset_index(drop=True)
    reasons = pd.Series([[] for _ in range(len(df))], index=df.index, dtype=object)

    for label, is_bad in rules:
        mask = is_bad(df).fillna(False).astype(bool)
        for idx in df.index[mask]:
            reasons[idx].append(label)

    duplicated = df.duplicated(subset=["city_id", "date"], keep="first")
    for idx in df.index[duplicated]:
        reasons[idx].append("duplicate city_id/date")

    bad = reasons.map(bool)
    rejected = pd.DataFrame(
        {
            "dataset": dataset,
            "city_id": df.loc[bad, "city_id"],
            "date": df.loc[bad, "date"],
            "reason": reasons[bad].map("; ".join),
            "record": df[bad].apply(_to_json, axis=1) if bad.any() else pd.Series(dtype=str),
        },
        columns=QUARANTINE_COLUMNS,
    ).reset_index(drop=True)
    return ValidationResult(valid=df[~bad].reset_index(drop=True), rejected=rejected)


def validate_weather(df: pd.DataFrame) -> ValidationResult:
    """Check daily weather rows against physical-range and consistency rules."""
    return _apply_rules(df, WEATHER_RULES, "weather")


def validate_air_quality(df: pd.DataFrame) -> ValidationResult:
    """Check daily air-quality rows against non-negativity and consistency rules."""
    return _apply_rules(df, AIR_RULES, "air_quality")
