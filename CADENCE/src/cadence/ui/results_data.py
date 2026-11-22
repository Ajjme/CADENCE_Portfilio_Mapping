"""Schema-safe, lazy access to immutable Alternative Analysis outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import polars as pl
import streamlit as st

from cadence.economics import run_results
from cadence.economics.run_export import build_run_workbook, portfolio_summary  # noqa: F401
# Shared with the FastAPI backend. Imported here too so the pages and tests can keep using these names.
from cadence.economics.run_results import (  # noqa: F401
    METRICS,
    PORTFOLIO_OPTION,
    SUMMARY_COLUMNS,
    SUPPORTED_SCHEMAS,
    cost_allocations,
)
from cadence.economics.temporary_policies import TEMPORARY_TILE_POLICY_ID
from cadence.reference_data.fragility import (
    CURVE_AGGREGATION_METHOD,
    CURVE_KEYS,
    FRAGILITY_MAPPING_VERSION,
    FRAGILITY_SNAPSHOT_VERSION,
    MATERIAL_PROXY_IDS,
    TERRAIN_LABELS,
    load_fragility_curves,
    validate_fragility_curves,
)
from cadence.reference_data.year1_damage import _fragility_identity
from cadence.ui.charts import MATERIAL_NAMES, SCENARIO_ORDER
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, FRAGILITY_ROOT
from cadence.ui.workbooks import sha256_file
from cadence.vulnerability.expected_damage import RETURN_PERIODS

MAP_REGIONS = {"ZIP / ZCTA": "zip_code", "County": "county_fips", "State": "state_code"}
MAP_METRICS = {
    "cumulative_avoided_damage_usd": "Cumulative avoided damage",
    "net_present_value_usd": "Final NPV",
}


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
    return run_results.check_run_metadata(Path(run_root), ALTERNATIVE_RESULTS_ROOT)


@st.cache_data(show_spinner=False)
def load_summary(run_root: str) -> pd.DataFrame:
    """Read the compact per-asset alternative summary."""
    load_run_metadata(run_root)
    return run_results.read_summary(Path(run_root), duckdb_connection())


@st.cache_data(show_spinner=False)
def load_asset_series(run_root: str, asset_id: str, metric: str) -> pd.DataFrame:
    """Load one metric and event state for one selected asset."""
    _validate_metric(metric)
    metadata = load_run_metadata(run_root)
    return run_results.read_asset_series(Path(run_root), metadata, asset_id, metric, duckdb_connection())


@st.cache_data(show_spinner=False)
def load_portfolio_series(run_root: str, metric: str) -> pd.DataFrame:
    """Sum a dollar metric only where every portfolio asset has a value."""
    _validate_metric(metric)
    metadata = load_run_metadata(run_root)
    return run_results.read_portfolio_series(Path(run_root), metadata, metric, duckdb_connection())


@st.cache_data(show_spinner=False)
def load_year_cost_rows(run_root: str, year: int, asset_id: str) -> pd.DataFrame:
    """Read effective scenario costs and source price shares for a selected year."""
    metadata = load_run_metadata(run_root)
    return run_results.read_year_cost_rows(Path(run_root), metadata, year, asset_id, duckdb_connection())


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


def load_fragility_results(run_root: str, asset_id: str, year: int) -> pd.DataFrame:
    """Expose the selected run's effective curves, never unverified current sources."""
    metadata = load_run_metadata(run_root)
    start = int(metadata["run_config"]["start_year"])
    end = int(metadata["run_config"]["end_year"])
    if year < start or year > end:
        raise ValueError(f"year {year} is outside the run's modeled years")
    root = Path(run_root).resolve()
    common = ["asset_id", "year", "scenario_id", "scenario_material_id", "lookup_roof_age", "age_capped"]
    state_columns = [
        *common, "roof_age_years", "installation_event", "burnout_replacement_event",
        "temporary_tile_metal_proxy_applied",
    ]
    damage_columns = [
        *common, "climate_zone", "terrain_id", "fragility_proxy_id",
        "fragility_mapping_version", "curve_aggregation_method",
    ]
    frames = []
    where = "" if asset_id == PORTFOLIO_OPTION else "WHERE asset_id = ?"
    params = [] if asset_id == PORTFOLIO_OPTION else [asset_id]
    for artifact, key, columns in (
        ("annual_scenario_state", "annual_state_path", state_columns),
        ("annual_scenario_damage", "annual_damage_path", damage_columns),
    ):
        partition = _fragility_partition(root, metadata, artifact, key, year)
        frames.append(duckdb_connection().execute(
            f"SELECT {', '.join(columns)} FROM read_parquet('{_sql_path(partition / '*.parquet')}') {where}",
            params,
        ).fetchdf())
    state, damage = frames
    identity = ["asset_id", "year", "scenario_id"]
    for frame in frames:
        if frame.empty or frame.isna().any().any() or frame.duplicated(identity).any():
            raise ValueError("fragility state/damage rows are missing, null, or duplicated")
    rows = state.merge(damage, on=common, how="outer", validate="one_to_one", indicator=True)
    if (rows["_merge"] != "both").any() or (rows["year"] != year).any():
        raise ValueError("fragility state and damage rows are inconsistent")
    rows = rows.drop(columns="_merge")
    summary_path = _sql_path(root / "alternative_summary.parquet")
    run_assets = set(duckdb_connection().execute(
        f"SELECT DISTINCT asset_id FROM read_parquet('{summary_path}')"
    ).fetchdf()["asset_id"])
    expected_assets = run_assets if asset_id == PORTFOLIO_OPTION else {asset_id}
    if not expected_assets.issubset(run_assets) or set(rows["asset_id"]) != expected_assets:
        raise ValueError("fragility results are missing for a selected asset")
    if any(set(group["scenario_id"]) != set(SCENARIO_ORDER) for _, group in rows.groupby("asset_id")):
        raise ValueError("fragility results require all four scenarios for every asset")
    if (
        not rows["scenario_material_id"].isin(MATERIAL_PROXY_IDS).all()
        or not rows["terrain_id"].isin(TERRAIN_LABELS).all()
        or not (rows["fragility_mapping_version"] == FRAGILITY_MAPPING_VERSION).all()
        or not (rows["curve_aggregation_method"] == CURVE_AGGREGATION_METHOD).all()
    ):
        raise ValueError("fragility results have unsupported mapping or terrain provenance")
    ages = rows["roof_age_years"].to_numpy(dtype=float)
    if (
        not np.isfinite(ages).all() or (ages < 0).any() or (ages != np.floor(ages)).any()
        or not np.array_equal(rows["lookup_roof_age"], np.clip(ages + 1, 1, 30))
        or not np.array_equal(rows["age_capped"], ages + 1 > 30)
    ):
        raise ValueError("fragility results have inconsistent chronological or lookup ages")
    tile = rows["scenario_id"] == "NEW_TILE"
    policy = metadata.get("temporary_tile_policy", {})
    if (
        policy.get("policy_id") != TEMPORARY_TILE_POLICY_ID
        or policy.get("lifecycle_and_vulnerability_source") != "NEW_METAL"
        or not np.array_equal(rows["temporary_tile_metal_proxy_applied"], tile)
    ):
        raise ValueError("fragility results have unsupported Tile proxy provenance")
    rows["source_material_id"] = rows["scenario_material_id"].where(~tile, "OFFICIAL_METAL")
    if not (rows["fragility_proxy_id"] == rows["source_material_id"].map(MATERIAL_PROXY_IDS)).all():
        raise ValueError("saved fragility proxy does not match the scenario's effective material")

    snapshot_fields = (
        "fragility_snapshot_version", "fragility_curves_path", "fragility_curves_checksum",
        "fragility_curve_point_count", "fragility_curve_key_count", "fragility_curve_aggregation_method",
    )
    if any(field in metadata for field in snapshot_fields):
        snapshot = root / "fragility_curves.parquet"
        if (
            metadata.get("fragility_snapshot_version") != FRAGILITY_SNAPSHOT_VERSION
            or metadata.get("fragility_curve_aggregation_method") != CURVE_AGGREGATION_METHOD
            or Path(str(metadata.get("fragility_curves_path", ""))).resolve() != snapshot
            or not snapshot.is_file()
        ):
            raise ValueError("declared fragility snapshot is missing or unsupported")
        checksum = sha256_file(snapshot)
        if checksum != metadata.get("fragility_curves_checksum"):
            raise ValueError("fragility snapshot checksum does not match the saved run")
        curves = _load_saved_fragility_curves(str(snapshot), checksum)
        if (
            len(curves) != metadata.get("fragility_curve_point_count")
            or len(curves[list(CURVE_KEYS)].drop_duplicates()) != metadata.get("fragility_curve_key_count")
        ):
            raise ValueError("fragility snapshot counts do not match the saved run")
        provenance = "Saved curve snapshot"
    else:
        for modeled_year in range(start, end + 1):
            _fragility_partition(root, metadata, "annual_scenario_damage", "annual_damage_path", modeled_year)
        pattern = _sql_path(root / "annual_scenario_damage" / "year=*" / "*.parquet")
        partitions = duckdb_connection().execute(
            f"SELECT DISTINCT climate_zone, lookup_roof_age FROM read_parquet('{pattern}', hive_partitioning=false)"
        ).pl()
        source_identity = _fragility_identity(partitions, FRAGILITY_ROOT)
        if source_identity != metadata.get("fragility_identity"):
            raise ValueError("legacy fragility sources no longer match the saved run; rerun the analysis")
        keys = rows[list(CURVE_KEYS)].drop_duplicates().sort_values(list(CURVE_KEYS)).reset_index(drop=True)
        curves = _load_verified_reference_curves(str(FRAGILITY_ROOT), keys, source_identity)
        provenance = "Identity-verified legacy reference"

    keys = list(CURVE_KEYS)
    available = curves[keys].drop_duplicates()
    matched = rows.merge(available, on=keys, how="left", validate="many_to_one", indicator=True)
    if (matched["_merge"] != "both").any():
        raise ValueError("fragility snapshot is missing a required scenario curve")
    points = curves[[*keys, "wind_speed_mph", "building_loss_ratio", "source_curve_count"]]
    result = rows.merge(points, on=keys, how="inner", validate="many_to_many")
    result["terrain_label"] = result["terrain_id"].map(TERRAIN_LABELS)
    result["curve_provenance"] = provenance
    return result.sort_values(["asset_id", "scenario_id", "wind_speed_mph"]).reset_index(drop=True)


def _fragility_partition(
    root: Path, metadata: dict[str, Any], artifact: str, metadata_key: str, year: int,
) -> Path:
    expected = root / artifact
    if Path(str(metadata.get(metadata_key, ""))).resolve() != expected:
        raise ValueError(f"{artifact} path does not match the selected run")
    partition = expected / f"year={year}"
    if not partition.is_dir() or not list(partition.glob("*.parquet")):
        raise ValueError(f"{artifact} results are missing for {year}")
    return partition


@st.cache_data(show_spinner=False)
def _load_saved_fragility_curves(path: str, checksum: str) -> pd.DataFrame:
    curves = pl.read_parquet(path)
    validate_fragility_curves(curves)
    return curves.to_pandas()


@st.cache_data(show_spinner=False)
def _load_verified_reference_curves(
    root: str, keys: pd.DataFrame, source_identity: str,
) -> pd.DataFrame:
    return load_fragility_curves(Path(root), pl.from_pandas(keys)).to_pandas()


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


@st.cache_data(show_spinner="Preparing the Excel file...")
def export_run_workbook(run_root: str) -> bytes:
    """The run as one Excel file, after the same checks the results page runs."""
    load_run_metadata(run_root)
    return build_run_workbook(Path(run_root))


def _annual_pattern(root: Path, metadata: dict[str, Any]) -> str:
    return run_results.annual_pattern(root, metadata)


def _validate_metric(metric: str) -> None:
    run_results.validate_metric(metric)


def _sql_path(path: Path) -> str:
    return run_results.sql_path(path)
