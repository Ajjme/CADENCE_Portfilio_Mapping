"""Schema-safe, lazy access to immutable Alternative Analysis outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st

from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT

SUPPORTED_SCHEMAS = {"v0.4.0"}
METRICS = {
    "annual_repair_cost_usd": "Annual repair cost",
    "annual_climate_risk_cost_usd": "Repair + loss of use",
    "annual_avoided_damage_usd": "Annual avoided damage",
    "cumulative_avoided_damage_usd": "Cumulative avoided damage",
    "cumulative_discounted_avoided_damage_usd": "Discounted avoided damage",
    "annual_net_benefit_usd": "Annual lifecycle net benefit",
    "cumulative_net_benefit_usd": "Cumulative lifecycle net benefit",
    "net_present_value_usd": "Net present value",
}
SUMMARY_COLUMNS = (
    "asset_id", "scenario_id", "scenario_material_id", "through_year",
    "cumulative_avoided_damage_usd",
    "cumulative_discounted_avoided_damage_usd",
    "cumulative_net_benefit_usd", "net_present_value_usd",
    "burnout_replacement_count", "active_cost_source",
    "active_cost_fallback_applied", "repair_cost_incomplete",
    "climate_risk_total_incomplete", "event_cost_incomplete",
)


@st.cache_resource
def duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Return the process-local analytical connection."""
    return duckdb.connect(database=":memory:")


@st.cache_data(show_spinner=False)
def discover_runs(results_root: str) -> list[dict[str, Any]]:
    """Return valid metadata records without choosing a newest run."""
    root = Path(results_root).resolve()
    runs = []
    for metadata_path in root.glob("schema_version=*/run_id=*/run_metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs.append(
            {
                "run_id": metadata.get("run_id"),
                "schema_version": metadata.get("schema_version"),
                "run_timestamp": metadata.get("run_timestamp"),
                "asset_count": metadata.get("asset_count"),
                "run_root": str(metadata_path.parent.resolve()),
            }
        )
    return sorted(runs, key=lambda row: str(row.get("run_timestamp") or ""), reverse=True)


@st.cache_data(show_spinner=False)
def load_run_metadata(run_root: str) -> dict[str, Any]:
    """Validate run identity, schema, location, and required artifacts."""
    root = Path(run_root).resolve()
    allowed = ALTERNATIVE_RESULTS_ROOT.resolve()
    if not root.is_relative_to(allowed):
        raise ValueError("selected run is outside the configured Alternative Analysis root")
    metadata_path = root / "run_metadata.json"
    if not metadata_path.is_file():
        raise ValueError(f"run metadata is missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    schema = metadata.get("schema_version")
    if schema not in SUPPORTED_SCHEMAS:
        supported = ", ".join(sorted(SUPPORTED_SCHEMAS))
        raise ValueError(f"unsupported result schema {schema!r}; supported schemas: {supported}")
    if root.name != f"run_id={metadata.get('run_id')}":
        raise ValueError("run directory does not match metadata run_id")
    if root.parent.name != f"schema_version={schema}":
        raise ValueError("schema directory does not match run metadata")
    for relative in (
        "alternative_summary.parquet",
        "annual_alternative_analysis",
    ):
        if not (root / relative).exists():
            raise ValueError(f"run artifact is missing: {relative}")
    return metadata


@st.cache_data(show_spinner=False)
def load_summary(run_root: str) -> pd.DataFrame:
    """Read the compact per-asset alternative summary."""
    load_run_metadata(run_root)
    path = _sql_path(Path(run_root) / "alternative_summary.parquet")
    columns = ", ".join(SUMMARY_COLUMNS)
    return duckdb_connection().execute(
        f"SELECT {columns} FROM read_parquet('{path}') ORDER BY asset_id, scenario_id"
    ).fetchdf()


@st.cache_data(show_spinner=False)
def load_asset_series(run_root: str, asset_id: str, metric: str) -> pd.DataFrame:
    """Load one metric and event state for one selected asset."""
    _validate_metric(metric)
    metadata = load_run_metadata(run_root)
    path = _annual_pattern(Path(run_root), metadata)
    return duckdb_connection().execute(
        f"""
        SELECT asset_id, year, scenario_id, official_current_material_id,
               {metric} AS metric_value, installation_event,
               initial_installation_event, burnout_replacement_event
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE asset_id = ?
        ORDER BY year, scenario_id
        """,
        [asset_id],
    ).fetchdf()


@st.cache_data(show_spinner=False)
def load_portfolio_series(run_root: str, metric: str) -> pd.DataFrame:
    """Sum a dollar metric only where every portfolio asset has a value."""
    _validate_metric(metric)
    metadata = load_run_metadata(run_root)
    path = _annual_pattern(Path(run_root), metadata)
    return duckdb_connection().execute(
        f"""
        SELECT year, scenario_id,
               CASE WHEN COUNT({metric}) = COUNT(*) THEN SUM({metric}) END AS metric_value,
               COUNT(*) - COUNT({metric}) AS missing_value_count,
               COUNT(*) AS expected_value_count,
               SUM(CASE WHEN installation_event THEN 1 ELSE 0 END) AS installation_event_count,
               SUM(CASE WHEN burnout_replacement_event THEN 1 ELSE 0 END) AS replacement_event_count
        FROM read_parquet('{path}', hive_partitioning=true)
        GROUP BY year, scenario_id
        ORDER BY year, scenario_id
        """
    ).fetchdf()


def portfolio_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Aggregate additive final outcomes without masking incomplete rows."""
    value_columns = [
        "cumulative_avoided_damage_usd",
        "cumulative_discounted_avoided_damage_usd",
        "cumulative_net_benefit_usd",
        "net_present_value_usd",
    ]
    flag_columns = [
        "active_cost_fallback_applied",
        "repair_cost_incomplete",
        "climate_risk_total_incomplete",
        "event_cost_incomplete",
    ]
    rows = []
    for scenario_id, group in summary.groupby("scenario_id", sort=True):
        row: dict[str, Any] = {
            "scenario_id": scenario_id,
            "asset_count": group["asset_id"].nunique(),
            "burnout_replacement_count": group["burnout_replacement_count"].sum(),
        }
        for column in value_columns:
            row[column] = group[column].sum() if group[column].notna().all() else None
        for column in flag_columns:
            row[column] = bool(group[column].fillna(True).any())
        rows.append(row)
    return pd.DataFrame(rows)


def _annual_pattern(root: Path, metadata: dict[str, Any]) -> str:
    configured = Path(str(metadata.get("annual_analysis_path", ""))).resolve()
    expected = (root / "annual_alternative_analysis").resolve()
    if configured != expected:
        raise ValueError("annual analysis path in metadata does not match the run directory")
    return _sql_path(expected / "year=*" / "*.parquet")


def _validate_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ValueError(f"unsupported Alternative Analysis metric: {metric}")


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")