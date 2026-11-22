"""Read one saved Alternative Analysis run: its metadata, summary, yearly values, and costs.

This is plain Python with no Streamlit in it, so the Streamlit results page
(cadence.ui.results_data) and the FastAPI backend (cadence.api) read runs the
same way. Each function takes the DuckDB connection to use, so callers decide
how connections are shared.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

SUPPORTED_SCHEMAS = {"v0.4.0"}
# Dunder form cannot collide with a workbook asset ID.
PORTFOLIO_OPTION = "__PORTFOLIO__"
SCENARIOS = ("BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
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
# Each year's cash flow split into parts that don't overlap, for the cost allocation chart.
COST_COMPONENTS = {
    "material_usd": "Material",
    "labor_usd": "Labor",
    "repair_usd": "Expected repair",
    "loss_of_use_usd": "Loss of use",
    "disposal_usd": "Disposal",
    "carbon_usd": "Carbon",
}


def check_run_metadata(run_root: Path, results_root: Path) -> dict[str, Any]:
    """Validate run identity, schema, location, and required artifacts, then return the metadata."""
    root = Path(run_root).resolve()
    allowed = Path(results_root).resolve()
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


def read_summary(run_root: Path, connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Read the compact per-asset alternative summary."""
    path = sql_path(Path(run_root) / "alternative_summary.parquet")
    columns = ", ".join(SUMMARY_COLUMNS)
    return connection.execute(
        f"SELECT {columns} FROM read_parquet('{path}') ORDER BY asset_id, scenario_id"
    ).fetchdf()


def read_asset_series(
    run_root: Path,
    metadata: dict[str, Any],
    asset_id: str,
    metric: str,
    connection: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Load one metric and event state for one selected asset."""
    validate_metric(metric)
    path = annual_pattern(Path(run_root), metadata)
    return connection.execute(
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


def read_portfolio_series(
    run_root: Path,
    metadata: dict[str, Any],
    metric: str,
    connection: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Sum a dollar metric only where every portfolio asset has a value."""
    validate_metric(metric)
    path = annual_pattern(Path(run_root), metadata)
    return connection.execute(
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


def read_year_cost_rows(
    run_root: Path,
    metadata: dict[str, Any],
    year: int,
    asset_id: str,
    connection: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Read effective scenario costs and source price shares for a selected year."""
    config = metadata["run_config"]
    if year not in range(int(config["start_year"]), int(config["end_year"]) + 1):
        raise ValueError(f"year {year} is outside the run's modeled years")
    root = Path(run_root).resolve()
    reference_id = metadata.get("economics_reference_run_id")
    if not isinstance(reference_id, str) or not reference_id or "/" in reference_id or ".." in reference_id:
        raise ValueError("run has no valid economics reference ID")
    reference_root = root.parents[1] / "economics_reference" / "schema_version=v0.3.0" / f"run_id={reference_id}"
    reference_metadata = reference_root / "run_metadata.json"
    reference_partition = reference_root / "annual_roof_option_costs" / f"year={year}"
    if not reference_metadata.is_file() or not list(reference_partition.glob("*.parquet")):
        raise ValueError("the linked economics reference costs are unavailable")
    reference = json.loads(reference_metadata.read_text(encoding="utf-8"))
    if reference.get("run_id") != reference_id or reference.get("schema_version") != "v0.3.0":
        raise ValueError("the linked economics reference does not match the selected run")
    analysis_partition = root / "annual_alternative_analysis" / f"year={year}"
    if not list(analysis_partition.glob("*.parquet")):
        raise ValueError(f"annual cost results are unavailable for {year}")
    condition = "WHERE a.asset_id = ?" if asset_id != PORTFOLIO_OPTION else ""
    parameters = [asset_id] if condition else []
    rows = connection.execute(
        f"""
        SELECT a.asset_id, a.year, a.scenario_id, a.scenario_material_id,
               a.official_current_material_id, a.installation_event,
               a.installation_event_capex_usd, a.annual_repair_cost_usd,
               a.expected_loss_of_use_usd, a.enabled_event_disposal_cost_usd,
               a.enabled_event_carbon_cost_usd, a.annual_lifecycle_cash_flow_usd,
               a.active_cost_source, a.active_cost_fallback_applied,
               r.source_material_usd_per_sqft, r.source_labor_usd_per_sqft
        FROM read_parquet('{sql_path(analysis_partition / '*.parquet')}') a
        LEFT JOIN read_parquet('{sql_path(reference_partition / '*.parquet')}') r
          ON a.asset_id = r.asset_id AND a.year = r.year
          AND (CASE WHEN a.scenario_id = 'NEW_TILE' THEN 'OFFICIAL_METAL'
                    ELSE a.scenario_material_id END) = r.official_material_id
        {condition}
        ORDER BY a.asset_id, a.scenario_id
        """,
        parameters,
    ).fetchdf()
    expected_scenarios = set(SCENARIOS)
    if (rows.empty or rows.groupby("asset_id").size().ne(4).any()
            or rows.duplicated(["asset_id", "scenario_id"]).any()
            or set(rows["scenario_id"]) != expected_scenarios
            or (asset_id == PORTFOLIO_OPTION and rows["asset_id"].nunique() != int(metadata["asset_count"]))):
        raise ValueError("annual cost rows are missing or duplicated for an asset")
    return rows


def cost_allocations(rows: pd.DataFrame, metadata: dict[str, Any], portfolio: bool) -> pd.DataFrame:
    """Allocate effective annual cash flow into exclusive component costs."""
    config = metadata["run_config"]
    enabled = set(config["enabled_cost_streams"])
    allocations = rows.copy()
    allocations["material_usd"] = 0.0
    allocations["labor_usd"] = 0.0
    allocations["allocation_estimated"] = False
    for index, row in allocations.loc[allocations["installation_event"]].iterrows():
        capex = row["installation_event_capex_usd"]
        if row["scenario_id"] == "NEW_TILE" and metadata.get("temporary_tile_policy"):
            share_material = row["source_material_usd_per_sqft"]
            share_labor = row["source_labor_usd_per_sqft"]
            if pd.isna(share_material) or pd.isna(share_labor):
                shares = config["installed_cost_overrides"]["OFFICIAL_METAL"]
                share_material, share_labor = shares["material_share"], shares["labor_share"]
            allocations.at[index, "allocation_estimated"] = True
        elif bool(row["active_cost_fallback_applied"]):
            shares = config["installed_cost_overrides"][row["scenario_material_id"]]
            share_material, share_labor = shares["material_share"], shares["labor_share"]
            allocations.at[index, "allocation_estimated"] = True
        else:
            share_material = row["source_material_usd_per_sqft"]
            share_labor = row["source_labor_usd_per_sqft"]
        denominator = share_material + share_labor
        if pd.isna(capex) or pd.isna(denominator) or denominator <= 0:
            allocations.at[index, "material_usd"] = float("nan")
            allocations.at[index, "labor_usd"] = float("nan")
        else:
            allocations.at[index, "material_usd"] = capex * share_material / denominator
            allocations.at[index, "labor_usd"] = capex - allocations.at[index, "material_usd"]
    allocations["repair_usd"] = allocations["annual_repair_cost_usd"]
    for stream, output, source in (
        ("loss_of_use", "loss_of_use_usd", "expected_loss_of_use_usd"),
        ("disposal", "disposal_usd", "enabled_event_disposal_cost_usd"),
        ("carbon", "carbon_usd", "enabled_event_carbon_cost_usd"),
    ):
        allocations[output] = allocations[source] if stream in enabled else 0.0
    components = list(COST_COMPONENTS)
    if portfolio:
        allocations = allocations.groupby("scenario_id", sort=True).agg(
            {**{column: lambda values: values.sum(min_count=len(values)) for column in components},
             "allocation_estimated": "any", "annual_lifecycle_cash_flow_usd":
             lambda values: values.sum(min_count=len(values))}
        ).reset_index()
    allocations["total_usd"] = allocations[components].sum(axis=1, min_count=len(components))
    return allocations


def annual_pattern(root: Path, metadata: dict[str, Any]) -> str:
    """The run's yearly results as a DuckDB file pattern, after checking the metadata points at them."""
    configured = Path(str(metadata.get("annual_analysis_path", ""))).resolve()
    expected = (Path(root) / "annual_alternative_analysis").resolve()
    if configured != expected:
        raise ValueError("annual analysis path in metadata does not match the run directory")
    return sql_path(expected / "year=*" / "*.parquet")


def validate_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ValueError(f"unsupported Alternative Analysis metric: {metric}")


def sql_path(path: Path) -> str:
    return Path(path).resolve().as_posix().replace("'", "''")
