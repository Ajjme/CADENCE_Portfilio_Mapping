"""Package one saved Alternative Analysis run as a single Excel workbook.

This is plain Python with no Streamlit in it, so the Streamlit download button
and the future FastAPI export endpoint can both call build_run_workbook.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterator

import duckdb
import numpy as np
import pandas as pd

# Excel sheets hold 1,048,576 rows, and one of them is the header.
EXCEL_MAX_ROWS = 1_048_575
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_DESCRIPTIONS = {
    "Portfolio summary": "Totals across all assets for each replacement option, through the last year",
    "Asset summary": "Final results for each asset and replacement option",
    "Annual results": "Every year of the analysis for each asset and replacement option",
    "Run settings": "The settings and sources the run used",
}
DOLLAR_BASIS_LABELS = {"real_2026_usd": "Real 2026 USD"}
PORTFOLIO_VALUE_COLUMNS = (
    "cumulative_avoided_damage_usd",
    "cumulative_discounted_avoided_damage_usd",
    "cumulative_net_benefit_usd",
    "net_present_value_usd",
)
PORTFOLIO_FLAG_COLUMNS = (
    "active_cost_fallback_applied",
    "repair_cost_incomplete",
    "climate_risk_total_incomplete",
    "event_cost_incomplete",
)


def build_run_workbook(run_root: Path) -> bytes:
    """Return an .xlsx file with the run's summaries, annual results, and settings."""
    root = Path(run_root)
    metadata_path = root / "run_metadata.json"
    summary_path = root / "alternative_summary.parquet"
    annual_root = root / "annual_alternative_analysis"
    for required in (metadata_path, summary_path, annual_root):
        if not required.exists():
            raise ValueError(f"run artifact is missing: {required.name}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    connection = duckdb.connect()
    summary = connection.execute(
        f"SELECT * FROM read_parquet('{_sql_path(summary_path)}') ORDER BY asset_id, scenario_id"
    ).fetchdf()
    annual = connection.execute(
        f"""
        SELECT * FROM read_parquet('{_sql_path(annual_root / "year=*" / "*.parquet")}', hive_partitioning=true)
        ORDER BY asset_id, scenario_id, year
        """
    ).fetchdf()
    if len(annual) > EXCEL_MAX_ROWS:
        raise ValueError(
            f"the annual results have {len(annual):,} rows, more than one Excel sheet holds "
            f"({EXCEL_MAX_ROWS:,})"
        )

    sheets = {
        "About": _about_sheet(metadata),
        "Portfolio summary": portfolio_summary(summary),
        "Asset summary": summary,
        "Annual results": annual,
        "Run settings": _settings_sheet(metadata),
    }
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            _excel_safe(frame).to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


def portfolio_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Aggregate additive final outcomes without masking incomplete rows."""
    rows = []
    for scenario_id, group in summary.groupby("scenario_id", sort=True):
        row: dict[str, Any] = {
            "scenario_id": scenario_id,
            "asset_count": group["asset_id"].nunique(),
            "burnout_replacement_count": group["burnout_replacement_count"].sum(),
        }
        for column in PORTFOLIO_VALUE_COLUMNS:
            row[column] = group[column].sum() if group[column].notna().all() else None
        for column in PORTFOLIO_FLAG_COLUMNS:
            row[column] = bool(group[column].fillna(True).any())
        rows.append(row)
    return pd.DataFrame(rows)


def _about_sheet(metadata: dict[str, Any]) -> pd.DataFrame:
    config = metadata.get("run_config") or {}
    years = (
        f"{config['start_year']}-{config['end_year']}"
        if "start_year" in config and "end_year" in config
        else ""
    )
    rows = [
        ("Run ID", metadata.get("run_id", "")),
        ("Run time (UTC)", metadata.get("run_timestamp", "")),
        ("Assets", metadata.get("asset_count", "")),
        ("Years", years),
        ("Dollars", DOLLAR_BASIS_LABELS.get(metadata.get("dollar_basis"), metadata.get("dollar_basis", ""))),
        ("", ""),
        *SHEET_DESCRIPTIONS.items(),
    ]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def _settings_sheet(metadata: dict[str, Any]) -> pd.DataFrame:
    # Paths point at folders on the server that ran the analysis, so they are left out.
    rows = [(key, value) for key, value in _flatten(metadata) if not key.endswith("_path")]
    return pd.DataFrame(rows, columns=["Setting", "Value"])


def _flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from _flatten(inner, f"{prefix}{key}.")
    else:
        yield prefix.rstrip("."), json.dumps(value) if isinstance(value, list) else value


def _excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Excel can't hold time zones, lists, or dicts, so convert those to plain values."""
    frame = frame.copy()
    for column in frame.columns:
        values = frame[column]
        if isinstance(values.dtype, pd.DatetimeTZDtype):
            frame[column] = values.dt.tz_convert("UTC").dt.tz_localize(None)
        elif values.dtype == object:
            frame[column] = values.map(_excel_cell)
    return frame


def _excel_cell(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")
