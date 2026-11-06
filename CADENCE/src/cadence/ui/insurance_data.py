"""Schema-checked DuckDB views over immutable insurance results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from cadence.insurance.pipeline import FORMULA_VERSION, INSURANCE_SCHEMA
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, RESULTS_ROOT
from cadence.ui.results_data import PORTFOLIO_OPTION, duckdb_connection, load_run_metadata

INSURANCE_ROOT = RESULTS_ROOT / "roof_insurance_analysis"


def discover_insurance_runs() -> list[dict[str, Any]]:
    """Discover only published insurance runs, including newly completed ones."""
    runs = []
    for path in INSURANCE_ROOT.glob("schema_version=*/run_id=*/run_metadata.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema_version") == INSURANCE_SCHEMA:
                runs.append({**data, "run_root": str(path.parent.resolve())})
        except (OSError, ValueError):
            continue
    return sorted(runs, key=lambda item: str(item.get("run_timestamp") or ""), reverse=True)


@st.cache_data(show_spinner=False)
def load_insurance_metadata(run_root: str) -> dict[str, Any]:
    """Check insurance schema, links and required artifacts before reading values."""
    root = Path(run_root).resolve()
    if not root.is_relative_to(INSURANCE_ROOT.resolve()):
        raise ValueError("insurance run is outside the configured results root")
    path = root / "run_metadata.json"
    if not path.is_file():
        raise ValueError("insurance run metadata is missing")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if (metadata.get("schema_version") != INSURANCE_SCHEMA
            or metadata.get("formula_version") != FORMULA_VERSION
            or root.parent.name != f"schema_version={INSURANCE_SCHEMA}"
            or root.name != f"run_id={metadata.get('run_id')}"):
        raise ValueError("unsupported or inconsistent insurance result schema")
    if metadata.get("physical_schema_version") != "v0.4.0":
        raise ValueError("insurance result uses an unsupported physical schema")
    physical_id = metadata.get("physical_run_id")
    if not isinstance(physical_id, str) or not physical_id or "/" in physical_id or ".." in physical_id:
        raise ValueError("insurance result has no valid physical run ID")
    physical_root = (ALTERNATIVE_RESULTS_ROOT / f"schema_version={metadata.get('physical_schema_version')}"
                     / f"run_id={physical_id}")
    physical = load_run_metadata(str(physical_root))
    if physical["run_id"] != physical_id or physical["asset_count"] != metadata.get("asset_count"):
        raise ValueError("insurance result does not match its physical run")
    for relative in ("policy_snapshot.parquet", "insurance_summary.parquet", "annual_insurance"):
        if not (root / relative).exists():
            raise ValueError(f"insurance run artifact is missing: {relative}")
    return metadata


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


@st.cache_data(show_spinner=False)
def load_policy_snapshot(run_root: str) -> pd.DataFrame:
    load_insurance_metadata(run_root)
    path = _sql_path(Path(run_root) / "policy_snapshot.parquet")
    return duckdb_connection().execute(
        f"SELECT asset_id, policy_id, insured_value, deductible_amount, "
        f"current_premium, policy_issue FROM read_parquet('{path}') ORDER BY asset_id"
    ).fetchdf()


@st.cache_data(show_spinner=False)
def load_insurance_series(run_root: str, asset_id: str) -> pd.DataFrame:
    """Load all years/scenarios for one asset or completeness-aware portfolio."""
    metadata = load_insurance_metadata(run_root)
    path = _sql_path(Path(run_root) / "annual_insurance" / "year=*" / "*.parquet")
    connection = duckdb_connection()
    columns = ("insured_value", "premium_usd", "expected_payout_usd",
               "underwriting_margin_usd", "cumulative_premium_usd",
               "cumulative_payout_usd", "cumulative_margin_usd")
    if asset_id != PORTFOLIO_OPTION:
        return connection.execute(
            f"SELECT asset_id, year, scenario_id, annual_repair_cost_usd, "
            f"deductible_amount, policy_id, insurance_issue, loss_ratio, "
            f"{', '.join(columns)} FROM read_parquet('{path}', hive_partitioning=true) "
            "WHERE asset_id = ? ORDER BY year, scenario_id", [asset_id]
        ).fetchdf()
    count = int(metadata["asset_count"])
    aggregates = ", ".join(
        f"CASE WHEN COUNT(*) = {count} AND COUNT({column}) = {count} "
        f"THEN SUM({column}) END AS {column}" for column in columns
    )
    return connection.execute(
        f"SELECT year, scenario_id, COUNT(insurance_issue) + ({count} - COUNT(*)) "
        f"AS missing_count, {aggregates} "
        f"FROM read_parquet('{path}', hive_partitioning=true) "
        "GROUP BY year, scenario_id ORDER BY year, scenario_id"
    ).fetchdf().assign(
        loss_ratio=lambda frame: frame["expected_payout_usd"] / frame["premium_usd"].where(
            frame["premium_usd"] > 0
        )
    )


@st.cache_data(show_spinner=False)
def load_insurance_issues(run_root: str, year: int, scenario_id: str) -> pd.DataFrame:
    load_insurance_metadata(run_root)
    path = _sql_path(Path(run_root) / "annual_insurance" / f"year={year}" / "*.parquet")
    return duckdb_connection().execute(
        f"SELECT asset_id, insurance_issue FROM read_parquet('{path}') "
        "WHERE scenario_id = ? AND insurance_issue IS NOT NULL ORDER BY asset_id",
        [scenario_id],
    ).fetchdf()