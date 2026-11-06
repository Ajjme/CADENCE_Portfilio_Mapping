"""Reconstruct single-home inputs from immutable physical run artifacts."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import polars as pl

from cadence.economics.alternative_analysis import build_annual_scenario_state
from cadence.economics.alternative_pipeline import _apply_temporary_tile_cost_policy, _source_paths
from cadence.economics.contracts import EconomicsRunConfig
from cadence.economics.externalities import build_scenario_event_costs
from cadence.economics.materials import build_material_mass_lookup
from cadence.economics.temporary_policies import TEMPORARY_TILE_POLICY_ID
from cadence.program.contracts import ProgramInputs, damage_state
from cadence.reference_data.fragility import CURVE_KEYS, load_fragility_curves, validate_fragility_curves
from cadence.vulnerability.annual_damage import HAZARD_COLUMNS


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_inputs(
    run_root: Path, asset_id: str, repository_root: Path, fragility_root: Path,
) -> ProgramInputs:
    """Use saved costs/hazard/state; only missing fragility keys use supplemental sources."""
    root = run_root.resolve()
    parent_path = root / "run_metadata.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if parent.get("schema_version") != "v0.4.0" or root.parent.name != "schema_version=v0.4.0":
        raise ValueError("Program View requires physical schema v0.4.0; rerun Alternative Analysis")
    if root.name != f"run_id={parent.get('run_id')}":
        raise ValueError("Physical run identity does not match its directory")
    config = EconomicsRunConfig.model_validate(parent["run_config"])
    policy = parent.get("temporary_tile_policy")
    if policy and policy.get("policy_id") != TEMPORARY_TILE_POLICY_ID:
        raise ValueError("Unsupported temporary Tile policy")
    source_checksums: Dict[str, str] = {"parent_metadata": sha256(parent_path)}

    def read_years(directory: Path, label: str) -> pl.DataFrame:
        frames = []
        for year in range(config.start_year, config.end_year + 1):
            files = sorted((directory / f"year={year}").glob("*.parquet"))
            if not files:
                raise ValueError(f"Missing {label} for {year}; rerun the matching Alternative Analysis")
            for path in files:
                source_checksums[f"{label}/{year}/{path.name}"] = sha256(path)
                frame = pl.read_parquet(path).filter(pl.col("asset_id") == asset_id)
                if frame.filter(pl.col("year") != year).height:
                    raise ValueError(f"{label} has inconsistent year partitions")
                frames.append(frame)
        return pl.concat(frames, how="vertical")

    state = read_years(root / "annual_scenario_state", "state")
    damage = read_years(root / "annual_scenario_damage", "damage")
    expected = {
        (year, scenario) for year in range(config.start_year, config.end_year + 1)
        for scenario in ("BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
    }
    for label, frame in (("state", state), ("damage", damage)):
        if frame.height != len(expected) or set(frame.select("year", "scenario_id").iter_rows()) != expected:
            raise ValueError(f"Saved {label} is missing or duplicates the selected home's scenarios")
    first = state.filter(pl.col("year") == config.start_year)
    asset_columns = [
        "asset_id", "official_current_material_id", "input_roof_age",
        "current_roof_eul_years", "roof_area_sqft", "state_code",
    ]
    assets = state.select(asset_columns).unique()
    if assets.height != 1 or not assets.equals(damage.select(asset_columns).unique()):
        raise ValueError("Saved physical asset inputs disagree")
    lives = first.filter(pl.col("scenario_role") == "new_alternative").select(
        pl.col("scenario_material_id").alias("official_material_id"),
        "raw_physical_eul_years", "applied_physical_eul_years",
        pl.col("service_life_mapping_version").alias("mapping_version"),
    ).sort("official_material_id")
    reference_id = parent.get("economics_reference_run_id")
    if not isinstance(reference_id, str) or not reference_id.isalnum():
        raise ValueError("Invalid linked economics reference")
    reference = root.parents[1] / "economics_reference/schema_version=v0.3.0" / f"run_id={reference_id}"
    reference_path = reference / "run_metadata.json"
    reference_metadata = json.loads(reference_path.read_text(encoding="utf-8"))
    if reference_metadata.get("run_id") != reference_id:
        raise ValueError("Economics reference identity mismatch")
    source_checksums["economics_metadata"] = sha256(reference_path)
    costs = read_years(reference / "annual_roof_option_costs", "option_costs")
    cost_keys = {(year, material) for year in range(config.start_year, config.end_year + 1)
                 for material in lives["official_material_id"]}
    if costs.height != len(cost_keys) or set(costs.select("year", "official_material_id").iter_rows()) != cost_keys:
        raise ValueError("Saved option costs are incomplete or duplicated")
    if costs.filter(
        (pl.col("roof_area_sqft") != assets["roof_area_sqft"][0])
        | (pl.col("official_current_material_id") != assets["official_current_material_id"][0])
    ).height:
        raise ValueError("Saved option costs do not match the selected home")
    # Reference option disposal prices describe removing the original roof,
    # not every future material. Rebuild event prices from verified sources.
    paths = _source_paths(repository_root)
    for name in ("material_mass", "mapping", "class_map", "disposal", "carbon", "scghg"):
        checksum = sha256(paths[name])
        if checksum != parent.get("source_checksums", {}).get(name):
            raise ValueError(f"Removal source {name} differs from the parent; rerun Alternative Analysis")
        source_checksums[f"removal_source/{name}"] = checksum
    event_state = costs.select(
        "asset_id", "year",
        pl.col("official_material_id").alias("scenario_id"),
        pl.col("official_material_id").alias("removed_material_id"),
        pl.lit(True).alias("installation_event"),
    )
    mass = build_material_mass_lookup(paths["material_mass"], paths["mapping"], paths["class_map"])
    removals = build_scenario_event_costs(
        event_state, assets, mass, config, paths["disposal"], paths["carbon"],
        paths["scghg"], paths["mapping"], paths["class_map"],
    ).select(
        "asset_id", "year", pl.col("removed_material_id").alias("official_material_id"),
        pl.col("event_disposal_cost_usd").alias("disposal_cost_usd"),
        pl.col("event_carbon_cost_usd").alias("carbon_cost_usd"),
    )
    if policy:
        costs = _apply_temporary_tile_cost_policy(costs)
    hazard = damage.select(HAZARD_COLUMNS).unique()
    if hazard.height != 1:
        raise ValueError("Saved hazard anchor is inconsistent")
    climate = damage.select("wind_grid_id", "year", "climate_scale_factor", "climate_scale_rule").unique()
    if climate.height != config.end_year - config.start_year + 1:
        raise ValueError("Saved annual climate factors are inconsistent")
    scheduled = pl.concat([
        build_annual_scenario_state(assets, lives, config, installation_year=year).with_columns(
            pl.lit(year).alias("candidate_year"),
        )
        for year in range(config.start_year, config.end_year + 1)
    ], how="vertical")
    required_curves = damage_state(scheduled, bool(policy)).select(
        "asset_id", "lookup_roof_age", pl.col("scenario_material_id").alias("source_material_id"),
    ).unique().join(hazard.select("asset_id", "climate_zone", "terrain_id"), on="asset_id", validate="m:1").select(CURVE_KEYS).unique()
    snapshot = root / "fragility_curves.parquet"
    if not snapshot.is_file() or parent.get("fragility_curves_checksum") != sha256(snapshot):
        raise ValueError("Physical fragility snapshot is missing or invalid; rerun Alternative Analysis")
    source_checksums["parent_fragility"] = sha256(snapshot)
    saved_curves = pl.read_parquet(snapshot)
    validate_fragility_curves(saved_curves)
    missing = required_curves.join(saved_curves.select(CURVE_KEYS).unique(), on=CURVE_KEYS, how="anti")
    curves = saved_curves.join(required_curves, on=CURVE_KEYS, how="semi")
    if missing.height:
        supplemental = load_fragility_curves(fragility_root, missing)
        curves = pl.concat([curves, supplemental], how="vertical")
    curves = curves.sort([*CURVE_KEYS, "wind_speed_mph"])
    validate_fragility_curves(curves)
    metadata: Dict[str, Any] = {
        "parent_run_id": parent["run_id"], "parent_run_root": str(root),
        "economics_reference_run_id": reference_id,
        "asset_id": asset_id, "source_checksums": source_checksums,
        "temporary_tile_policy": policy,
        "supplemental_fragility_key_count": missing.height,
        "supplemental_fragility_source": str(fragility_root.resolve()) if missing.height else None,
        "fragility_provenance": "Parent curves retained; missing candidate-path curves snapshotted from supplemental source",
    }
    return ProgramInputs(config, metadata, assets, lives, costs, removals, hazard, climate, curves, scheduled)
