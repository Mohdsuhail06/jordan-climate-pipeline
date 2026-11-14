"""Analytics layer: run the bundled SQL queries and write a Markdown report with charts."""

from __future__ import annotations

import datetime as dt
from importlib import resources
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # render to files, no window needed
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

QUERIES = (
    "city_summary",
    "monthly_pm25",
    "worst_dust_days",
    "rain_vs_air",
    "pm25_categories",
    "seasonal_temperature",
)

CATEGORY_ORDER = [
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
]
CATEGORY_COLORS = ["#2e7d32", "#f9a825", "#ef6c00", "#c62828", "#6a1b9a", "#4e342e"]
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_sql(name: str) -> str:
    """Read a bundled SQL file by name (without the .sql extension)."""
    if name not in QUERIES:
        raise KeyError(f"Unknown query '{name}'. Available: {', '.join(QUERIES)}")
    return resources.files("climate_pipeline").joinpath(f"sql/{name}.sql").read_text("utf-8")


def run_query(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    """Run a bundled query and return the result as a DataFrame."""
    return con.execute(load_sql(name)).df()


def to_markdown(df: pd.DataFrame) -> str:
    """Render a DataFrame as a GitHub-flavoured Markdown table (no extra dependency)."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    divider = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, divider, *rows])


def _plot_monthly_pm25(df: pd.DataFrame, path: Path) -> None:
    pivot = df.pivot(index="month", columns="city", values="avg_pm25")
    fig, ax = plt.subplots(figsize=(10, 5))
    pivot.plot(ax=ax, marker="o", linewidth=1.8)
    ax.axhline(15, color="grey", linestyle="--", linewidth=1, label="WHO daily guideline (15)")
    ax.set_xticks(range(1, 13), MONTHS)
    ax.set_xlabel("")
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.set_title("Average PM2.5 by month")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _plot_categories(df: pd.DataFrame, path: Path) -> None:
    pivot = df.pivot(index="city", columns="category", values="days").fillna(0)
    present = [c for c in CATEGORY_ORDER if c in pivot.columns]
    share = pivot[present].div(pivot[present].sum(axis=1), axis=0) * 100
    colors = [CATEGORY_COLORS[CATEGORY_ORDER.index(c)] for c in present]
    fig, ax = plt.subplots(figsize=(10, 5))
    share.sort_values(present[0]).plot.barh(ax=ax, stacked=True, color=colors, width=0.7)
    ax.set_xlabel("% of days")
    ax.set_ylabel("")
    ax.set_title("Share of days in each EPA PM2.5 category")
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _plot_temperature(df: pd.DataFrame, path: Path) -> None:
    pivot = df.pivot(index="city", columns="season", values="avg_temp_c")
    pivot = pivot[[s for s in SEASON_ORDER if s in pivot.columns]]
    fig, ax = plt.subplots(figsize=(10, 5))
    pivot.plot.bar(ax=ax, color=["#1565c0", "#43a047", "#e53935", "#fb8c00"][: pivot.shape[1]])
    ax.set_ylabel("Average temperature (°C)")
    ax.set_xlabel("")
    ax.set_title("Average temperature by city and season")
    ax.tick_params(axis="x", rotation=0)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(title="", loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=4, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def build_report(con: duckdb.DuckDBPyConnection, out_dir: Path) -> Path:
    """Write REPORT.md and three PNG charts to `out_dir`. Returns the report path.

    Raises:
        RuntimeError: if the warehouse has no data to report on.
    """
    n_weather = con.execute("SELECT count(*) FROM fact_weather_daily").fetchone()[0]
    n_air = con.execute("SELECT count(*) FROM fact_air_quality_daily").fetchone()[0]
    if n_weather == 0 or n_air == 0:
        raise RuntimeError("The warehouse has no data yet. Run the pipeline first.")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {name: run_query(con, name) for name in QUERIES}

    _plot_monthly_pm25(results["monthly_pm25"], out_dir / "monthly_pm25.png")
    _plot_categories(results["pm25_categories"], out_dir / "pm25_categories.png")
    _plot_temperature(results["seasonal_temperature"], out_dir / "temperature_by_city.png")

    first, last = con.execute("SELECT min(date), max(date) FROM fact_weather_daily").fetchone()
    lines = [
        "# Jordan Climate & Air Quality Report",
        "",
        f"Period: **{first} to {last}** · Weather rows: **{n_weather:,}** · "
        f"Air-quality rows: **{n_air:,}** · Generated: {dt.date.today()}",
        "",
        "## City summary",
        "",
        "`pct_days_above_who`: days with PM2.5 above the WHO daily guideline (15 µg/m³). "
        "`pct_unhealthy_days`: days above 35.4 µg/m³ (EPA *Unhealthy for Sensitive Groups* "
        "or worse).",
        "",
        to_markdown(results["city_summary"]),
        "",
        "## Seasonal pattern of fine particles (PM2.5)",
        "",
        "![Monthly PM2.5](monthly_pm25.png)",
        "",
        "## How often is the air unhealthy?",
        "",
        "![PM2.5 categories](pm25_categories.png)",
        "",
        "## Temperature by season",
        "",
        "![Temperature](temperature_by_city.png)",
        "",
        "## Ten dustiest days (highest PM10)",
        "",
        to_markdown(results["worst_dust_days"]),
        "",
        "## Does rain clean the air?",
        "",
        to_markdown(results["rain_vs_air"]),
        "",
    ]
    report = out_dir / "REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report
