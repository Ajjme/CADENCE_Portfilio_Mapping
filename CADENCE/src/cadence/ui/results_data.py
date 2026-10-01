"""Schema-safe, lazy access to immutable Alternative Analysis outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

from cadence.ui.charts import COST_COMPONENTS, MATERIAL_NAMES
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT
from cadence.vulnerability.expected_damage import RETURN_PERIODS

SUPPORTED_SCHEMAS = {"v0.4.0"}
# Dunder form cannot collide with a workbook asset ID.
PORTFOLIO_OPTION = "__PORTFOLIO__"
MAP_REGIONS = {"ZIP / ZCTA": "zip_code", "County": "county_fips", "State": "state_code"}
MAP_METRICS = {
    "cumulative_avoided_damage_usd": "Cumulative avoided damage",
    "net_present_value_usd": "Final NPV",
}
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


@st.cache_data(show_spinner=False)
def load_year_cost_rows(run_root: str, year: int, asset_id: str) -> pd.DataFrame:
    """Read effective scenario costs and source price shares for a selected year."""
    metadata = load_run_metadata(run_root)
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
    rows = duckdb_connection().execute(
        f"""
        SELECT a.asset_id, a.year, a.scenario_id, a.scenario_material_id,
               a.official_current_material_id, a.installation_event,
               a.installation_event_capex_usd, a.annual_repair_cost_usd,
               a.expected_loss_of_use_usd, a.enabled_event_disposal_cost_usd,
               a.enabled_event_carbon_cost_usd, a.annual_lifecycle_cash_flow_usd,
               a.active_cost_source, a.active_cost_fallback_applied,
               r.source_material_usd_per_sqft, r.source_labor_usd_per_sqft
        FROM read_parquet('{_sql_path(analysis_partition / '*.parquet')}') a
        LEFT JOIN read_parquet('{_sql_path(reference_partition / '*.parquet')}') r
          ON a.asset_id = r.asset_id AND a.year = r.year
          AND (CASE WHEN a.scenario_id = 'NEW_TILE' THEN 'OFFICIAL_METAL'
                    ELSE a.scenario_material_id END) = r.official_material_id
        {condition}
        ORDER BY a.asset_id, a.scenario_id
        """,
        parameters,
    ).fetchdf()
    expected_scenarios = {"BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE"}
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


@st.cache_data(show_spinner=False)
def load_current_materials(run_root: str) -> pd.DataFrame:
    """Return each asset's installed official material."""
    metadata = load_run_metadata(run_root)
    path = _annual_pattern(Path(run_root), metadata)
    return duckdb_connection().execute(
        f"""
        SELECT DISTINCT asset_id, official_current_material_id
        FROM read_parquet('{path}', hive_partitioning=true)
        ORDER BY asset_id
        """
    ).fetchdf()


@st.cache_data(show_spinner=False)
def load_wind_return_periods(
    run_root: str, asset_id: str, year: int | None = None
) -> pd.DataFrame:
    """Read the matched grid's mph gusts from the selected run."""
    metadata = load_run_metadata(run_root)
    start_year = int(metadata["run_config"]["start_year"])
    end_year = int(metadata["run_config"]["end_year"])
    if year is not None and (year < start_year or year > end_year):
        raise ValueError(f"year {year} is outside the run's modeled years")
    root = Path(run_root).resolve()
    expected = (root / "annual_scenario_damage").resolve()
    if Path(str(metadata.get("annual_damage_path", ""))).resolve() != expected:
        raise ValueError("annual damage path in metadata does not match the run directory")
    partition = expected / f"year={start_year if year is None else year}"
    if not partition.is_dir() or not list(partition.glob("*.parquet")):
        raise ValueError(f"wind return-period results are missing for {year or 'baseline'}")
    prefix = "rp_" if year is None else "climate_scaled_rp_"
    gusts = [f"{prefix}{period}_3sec_gust" for period in RETURN_PERIODS]
    columns = ", ".join(["asset_id", "wind_grid_id", *gusts])
    where = "" if asset_id == PORTFOLIO_OPTION else "WHERE asset_id = ?"
    params = [] if asset_id == PORTFOLIO_OPTION else [asset_id]
    rows = duckdb_connection().execute(
        f"SELECT DISTINCT {columns} FROM read_parquet('{_sql_path(partition / '*.parquet')}') "
        f"{where} ORDER BY asset_id",
        params,
    ).fetchdf()
    expected_count = (
        int(metadata["asset_count"]) if asset_id == PORTFOLIO_OPTION else 1
    )
    if len(rows) != expected_count or rows["asset_id"].nunique() != expected_count:
        raise ValueError("wind return-period values are missing or inconsistent for an asset")
    values = rows[gusts].to_numpy(dtype=float)
    if rows["wind_grid_id"].isna().any() or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("wind return-period values or matched grid IDs are invalid")
    return rows.rename(columns=dict(zip(gusts, (f"rp_{period}" for period in RETURN_PERIODS))))


@st.cache_data(show_spinner=False, ttl=86400)
def load_map_geography(run_root: str) -> pd.DataFrame:
    """Read geography from the selected immutable run, independent of session state."""
    metadata = load_run_metadata(run_root)
    root = Path(run_root).resolve()
    expected = root / "annual_scenario_damage"
    if Path(str(metadata.get("annual_damage_path", ""))).resolve() != expected:
        raise ValueError("annual damage path does not match the selected run")
    partition = expected / f"year={int(metadata['run_config']['start_year'])}"
    if not list(partition.glob("*.parquet")):
        raise ValueError("saved run geography is unavailable")
    path = _sql_path(partition / "*.parquet")
    columns = ["asset_id", "latitude", "longitude", *MAP_REGIONS.values()]
    available = duckdb_connection().execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchdf()
    if not set(columns).issubset(available["column_name"]):
        raise ValueError("this older run does not contain saved map geography; run the portfolio again")
    rows = duckdb_connection().execute(
        f"SELECT DISTINCT {', '.join(columns)} FROM read_parquet('{path}') ORDER BY asset_id"
    ).fetchdf()
    if len(rows) != int(metadata["asset_count"]) or rows["asset_id"].duplicated().any():
        raise ValueError("saved geography is missing or inconsistent for an asset")
    if (not np.isfinite(rows[["latitude", "longitude"]].to_numpy(dtype=float)).all()
            or not rows["latitude"].between(-90, 90).all()
            or not rows["longitude"].between(-180, 180).all()):
        raise ValueError("saved map coordinates are invalid")
    return rows


def map_outcomes(summary: pd.DataFrame, geography: pd.DataFrame, metric: str, scenario: str) -> pd.DataFrame:
    """Select independent best replacement outcomes with deterministic ties."""
    alternatives = ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
    if metric not in MAP_METRICS or scenario not in ("BEST", *alternatives):
        raise ValueError("unsupported map selection")
    if set(summary["asset_id"]) != set(geography["asset_id"]):
        raise ValueError("map geography does not match the selected result assets")
    rows = summary.loc[summary["scenario_id"].isin(alternatives)].copy()
    if rows.duplicated(["asset_id", "scenario_id"]).any():
        raise ValueError("duplicate map outcome rows")
    rows[list(MAP_METRICS)] = rows[list(MAP_METRICS)].replace([np.inf, -np.inf], np.nan)
    if scenario == "BEST":
        complete = rows.groupby("asset_id")[metric].count().eq(len(alternatives))
        rows = rows.sort_values(["asset_id", metric, "scenario_id"], ascending=[True, False, True], na_position="last")
        rows = rows.drop_duplicates("asset_id").copy()
        incomplete = ~rows["asset_id"].map(complete).fillna(False)
        rows.loc[incomplete, list(MAP_METRICS)] = np.nan
        rows.loc[incomplete, "scenario_id"] = "Unavailable"
    else:
        rows = rows.loc[rows["scenario_id"] == scenario]
    return geography.merge(rows, on="asset_id", how="left", validate="1:1")


def regional_map_outcomes(rows: pd.DataFrame, metric: str, region: str, average: bool) -> pd.DataFrame:
    """Aggregate only complete selected outcomes within each geographic region."""
    if metric not in MAP_METRICS or region not in MAP_REGIONS:
        raise ValueError("unsupported regional map selection")
    field = MAP_REGIONS[region]
    grouped = rows.groupby(field, dropna=True)
    result = grouped.agg(asset_count=("asset_id", "size"), valid_count=(metric, "count"))
    result["missing_count"] = result["asset_count"] - result.pop("valid_count")
    result["value"] = grouped[metric].mean() if average else grouped[metric].sum(min_count=1)
    result.loc[result["missing_count"] > 0, "value"] = np.nan
    result["replacement_mix"] = grouped["scenario_id"].agg(
        lambda values: ", ".join(f"{name}: {count}" for name, count in values.fillna("Unavailable").value_counts().items())
    )
    return result.reset_index()


def asset_options(asset_ids: list[str]) -> list[str]:
    """Return dropdown options with the portfolio first."""
    return [PORTFOLIO_OPTION, *sorted(asset_ids)]


def material_mix_label(materials: pd.DataFrame) -> str:
    """Summarize installed roof counts by material in canonical order."""
    counts = (
        materials.drop_duplicates("asset_id")["official_current_material_id"]
        .astype(str)
        .value_counts()
    )
    order = [*MATERIAL_NAMES, *sorted(set(counts.index) - set(MATERIAL_NAMES))]
    parts = [
        f"{MATERIAL_NAMES.get(material_id, material_id)} {int(counts[material_id]):,}"
        for material_id in order
        if material_id in counts
    ]
    return " · ".join(["Installed roofs", *parts])


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