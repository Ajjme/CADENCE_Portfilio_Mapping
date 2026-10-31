"""Verified saved-run inputs for insurance-only event simulations."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from cadence.insurance.event_analysis import EventSettings
from cadence.insurance.event_pipeline import publish_event
from cadence.reference_data.economics_assets import FIPS_TO_STATE
from cadence.ui.insurance_data import load_insurance_metadata
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, RESULTS_ROOT
from cadence.ui.results_data import (
    PORTFOLIO_OPTION, load_fragility_results, load_run_metadata,
)
from cadence.ui.workbooks import sha256_file

EVENT_ROOT = RESULTS_ROOT / "roof_insurance_event_analysis"


def physical_root_for_insurance(run_root: str) -> Path:
    metadata = load_insurance_metadata(run_root)
    return ALTERNATIVE_RESULTS_ROOT / "schema_version=v0.4.0" / f"run_id={metadata['physical_run_id']}"


def _partition(root: Path, metadata: dict, artifact: str, key: str, year: int) -> list[Path]:
    path = root / artifact
    if Path(str(metadata.get(key, ""))).resolve() != path.resolve():
        raise ValueError(f"saved {artifact} path does not match the physical run")
    files = sorted((path / f"year={year}").glob("*.parquet"))
    if not files:
        raise ValueError(f"saved {artifact} is unavailable for {year}; rerun the portfolio")
    return files


def _geography(damage: pl.DataFrame) -> pl.DataFrame:
    columns = ["asset_id", "state_code", "latitude", "longitude"]
    frame = damage.with_columns(
        *(pl.lit(None, dtype=pl.String if name == "state_code" else pl.Float64).alias(name)
          for name in columns[1:] if name not in damage.columns)
    )
    frame = frame.select(columns).unique()
    if frame["asset_id"].n_unique() != frame.height:
        raise ValueError("saved event geography is inconsistent for an asset")
    return frame.with_columns(
        pl.when(pl.col("state_code").cast(pl.String).str.strip_chars().str.to_uppercase().is_in(list(FIPS_TO_STATE.values())))
        .then(pl.col("state_code").cast(pl.String).str.strip_chars().str.to_uppercase())
        .otherwise(None).alias("state_code"),
        *(pl.when(pl.col(name).cast(pl.Float64, strict=False).is_finite())
          .then(pl.col(name).cast(pl.Float64, strict=False)).otherwise(None).alias(name)
          for name in ("latitude", "longitude")),
    )


def run_event(run_root: str, settings: EventSettings) -> dict:
    insurance = load_insurance_metadata(run_root)
    root = physical_root_for_insurance(run_root)
    physical = load_run_metadata(str(root))
    if not int(insurance["year_start"]) <= settings.year <= int(insurance["year_end"]):
        raise ValueError("event year is outside the saved run horizon")
    damage_files = _partition(root, physical, "annual_scenario_damage", "annual_damage_path", settings.year)
    cost_files = _partition(root, physical, "annual_alternative_analysis", "annual_analysis_path", settings.year)
    damage = pl.read_parquet(damage_files, hive_partitioning=False)
    costs = pl.read_parquet(cost_files, hive_partitioning=False)
    policy_path = Path(run_root) / "policy_snapshot.parquet"
    policies = pl.read_parquet(policy_path)
    keys = ["asset_id", "year", "scenario_id"]
    if not set(keys).issubset(damage.columns) or not {*keys, "active_installed_capex_usd"}.issubset(costs.columns):
        raise ValueError("saved event damage or full roof costs are unavailable; rerun the portfolio")
    expected_ids = set(policies["asset_id"])
    for frame in (damage, costs):
        if (frame.unique(keys).height != frame.height
                or set(frame["asset_id"]) != expected_ids
                or frame.height != len(expected_ids) * 4
                or set(frame["year"]) != {settings.year}):
            raise ValueError("event source rows are missing, duplicated, or inconsistent")
    geography = _geography(damage)
    inputs = damage.drop(["state_code", "latitude", "longitude"], strict=False).join(
        geography, on="asset_id", validate="m:1"
    ).join(
        costs.select(*keys, "active_installed_capex_usd"), on=keys, how="left", validate="1:1"
    ).join(policies, on="asset_id", how="left", validate="m:1")
    curves = None
    source_files = [*damage_files, *cost_files, policy_path, root / "run_metadata.json", Path(run_root) / "run_metadata.json"]
    if settings.return_period == 300:
        curves = pl.from_pandas(load_fragility_results(str(root), PORTFOLIO_OPTION, settings.year))
        for path in (root / "fragility_curves.parquet",):
            if path.exists():
                source_files.append(path)
    provenance = {
        "physical_run_id": physical["run_id"], "insurance_run_id": insurance["run_id"],
        "policy_checksum": insurance["policy_checksum"],
        "source_checksums": {str(path.resolve()): sha256_file(path) for path in source_files},
    }
    return publish_event(inputs, settings, provenance, EVENT_ROOT, curves)
