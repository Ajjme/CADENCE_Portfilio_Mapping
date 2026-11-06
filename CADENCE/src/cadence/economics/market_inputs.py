"""Read immutable Alternative Analysis inputs for dynamic roof states."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from math import floor
from pathlib import Path
from typing import Callable

import polars as pl

from cadence.economics.contracts import CostStream, EconomicsRunConfig
from cadence.economics.alternative_pipeline import _source_paths
from cadence.economics.externalities import build_scenario_event_costs
from cadence.economics.materials import build_material_mass_lookup
from cadence.economics.market_study import MATERIALS
from cadence.economics.temporary_policies import TEMPORARY_TILE_COST_MULTIPLIER, TEMPORARY_TILE_POLICY_ID
from cadence.reference_data.fragility import CURVE_KEYS, load_fragility_curves
from cadence.ui.paths import CADENCE_ROOT, FRAGILITY_ROOT
from cadence.vulnerability.annual_damage import GUST_COLUMNS, SCALED_GUST_COLUMNS
from cadence.vulnerability.expected_damage import integrate_damage_matrix, interpolate_return_period_damage


REMOVAL_SOURCES = ("material_mass", "mapping", "class_map", "disposal", "carbon", "scghg")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def study_source_identity(root: Path, metadata: dict) -> dict[str, str]:
    """Hash saved inputs and verify the supplemental removal sources."""
    reference_id = metadata["economics_reference_run_id"]
    if not isinstance(reference_id, str) or not reference_id.isalnum():
        raise ValueError("Invalid linked economics reference")
    reference = root.parents[1] / "economics_reference/schema_version=v0.3.0" / f"run_id={reference_id}"
    identity = {"reference_metadata": file_sha256(reference / "run_metadata.json")}
    for label, directory in (("state", root / "annual_scenario_state"),
                             ("damage", root / "annual_scenario_damage"),
                             ("prices", reference / "annual_roof_option_costs")):
        files = sorted(directory.glob("year=*/*.parquet"))
        if not files:
            raise ValueError(f"Missing saved market {label}")
        for path in files:
            identity[f"{label}/{path.relative_to(directory)}"] = file_sha256(path)
    paths = _source_paths(CADENCE_ROOT)
    for name in REMOVAL_SOURCES:
        checksum = file_sha256(paths[name])
        if checksum != metadata.get("source_checksums", {}).get(name):
            raise ValueError(f"Removal source {name} differs from the parent; rerun Alternative Analysis")
        identity[f"removal/{name}"] = checksum
    return identity


def load_study_inputs(
    run_root: Path, assets_path: Path, metadata: dict, damage_path: Path | None = None,
    snapshot_root: Path | None = None,
) -> tuple[pl.DataFrame, dict, dict, dict, Callable[[str, int, str, int], tuple[float, float]]]:
    """Return selected assets, option prices, removal prices, service lives, and risk lookup."""
    root = run_root.resolve()
    if not assets_path.is_file() or assets_path.name != "economics_assets.parquet":
        raise ValueError("The active run has no saved economics asset snapshot")
    assets = pl.read_parquet(assets_path)
    required = {"asset_id", "input_roof_age", "official_current_material_id", "roof_area_sqft"}
    if not required.issubset(assets.columns) or assets["asset_id"].n_unique() != assets.height:
        raise ValueError("The active asset snapshot is invalid")
    if "current_roof_eul_years" not in assets.columns:
        assets = assets.with_columns(pl.lit(None, dtype=pl.Float64).alias("current_roof_eul_years"))
    reference_id = metadata["economics_reference_run_id"]
    if not isinstance(reference_id, str) or not reference_id.isalnum():
        raise ValueError("Invalid linked economics reference")
    reference = root.parents[1] / "economics_reference/schema_version=v0.3.0" / f"run_id={reference_id}"
    if not (reference / "run_metadata.json").is_file() or json.loads((reference / "run_metadata.json").read_text())["run_id"] != reference_id:
        raise ValueError("Linked economics reference is missing or inconsistent")
    costs = pl.read_parquet(str(reference / "annual_roof_option_costs/year=*/*.parquet"), hive_partitioning=False)
    state = pl.read_parquet(str(root / "annual_scenario_state/year=*/*.parquet"), hive_partitioning=False)
    damage = pl.read_parquet(str(root / "annual_scenario_damage/year=*/*.parquet"), hive_partitioning=False)
    baseline = damage.filter(pl.col("scenario_id") == "BASELINE_CURRENT")
    if (set(assets["asset_id"].to_list()) != set(baseline["asset_id"].to_list())
            or set(assets["asset_id"].to_list()) != set(costs["asset_id"].to_list())):
        raise ValueError("Saved assets, damage, and economics reference do not match")
    first_baseline = baseline.filter(pl.col("year") == int(metadata["run_config"]["start_year"]))
    compare = assets.select("asset_id", "latitude", "longitude", "roof_area_sqft", "official_current_material_id", "input_roof_age").join(
        first_baseline.select("asset_id", *(
            pl.col(column).alias(f"saved_{column}") for column in
            ("latitude", "longitude", "roof_area_sqft", "official_current_material_id", "input_roof_age")
        )), on="asset_id", how="left", validate="1:1",
    )
    if compare.height != assets.height or any(
        compare.select((pl.col(column) != pl.col(f"saved_{column}")).any()).item()
        for column in ("latitude", "longitude", "roof_area_sqft", "official_current_material_id", "input_roof_age")
    ):
        raise ValueError("Active asset snapshot does not match the selected run's saved asset fields")
    if damage_path is not None:
        source_damage = pl.read_parquet(damage_path).select("asset_id", "wind_grid_id", *GUST_COLUMNS).unique()
        matched = first_baseline.select("asset_id", "wind_grid_id", *GUST_COLUMNS).unique()
        if source_damage.height != assets.height or matched.join(
            source_damage, on=["asset_id", "wind_grid_id", *GUST_COLUMNS], how="inner", validate="1:1"
        ).height != assets.height:
            raise ValueError("Active year-one hazard does not match the selected run")
    config = EconomicsRunConfig.model_validate(metadata["run_config"])
    tile_proxy = bool(metadata.get("temporary_tile_policy"))
    if tile_proxy and metadata["temporary_tile_policy"].get("policy_id") != TEMPORARY_TILE_POLICY_ID:
        raise ValueError("Unsupported temporary Tile policy")
    if CostStream.LOSS_OF_USE in config.enabled_cost_streams:
        raise ValueError("Market Study requires verified annual loss-of-use input when enabled")
    expected_years = set(range(config.start_year, config.end_year + 1))
    if (set(baseline["year"].to_list()) != expected_years
            or baseline.height != assets.height * len(expected_years)
            or baseline.select("asset_id", "year").unique().height != baseline.height):
        raise ValueError("Annual baseline hazard is missing or duplicated")
    if (costs.height != assets.height * len(expected_years) * len(MATERIALS)
            or set(costs["year"].to_list()) != expected_years
            or set(costs["official_material_id"].to_list()) != set(MATERIALS)
            or costs.select("asset_id", "year", "official_material_id").unique().height != costs.height):
        raise ValueError("Annual option prices are missing or duplicated")
    first = state.filter(pl.col("year") == config.start_year)
    lives = {asset_id: {} for asset_id in assets["asset_id"].to_list()}
    for row in first.iter_rows(named=True):
        if row["scenario_id"] in ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE"):
            lives[row["asset_id"]][row["scenario_id"].replace("NEW_", "OFFICIAL_")] = int(row["applied_physical_eul_years"])
    if any(set(lives[asset_id]) != set(MATERIALS) for asset_id in lives):
        raise ValueError("Service life lookup is incomplete")
    prices: dict[str, dict] = {asset_id: {} for asset_id in lives}
    removals: dict[str, dict] = {asset_id: {} for asset_id in lives}
    for row in costs.iter_rows(named=True):
        asset_id, year, material = row["asset_id"], int(row["year"]), row["official_material_id"]
        if (material not in MATERIALS or year not in expected_years
            or (material == "OFFICIAL_TILE" and tile_proxy)):
            continue
        area, installed = float(row["roof_area_sqft"]), float(row["installed_capex_usd"])
        fallback = row["operational_cost_fallback_applied"]
        if fallback:
            material_cost = installed * float(row["override_material_share"])
        else:
            material_cost = area * float(row["source_material_usd_per_sqft"])
        labor_cost = installed - material_cost
        prices[asset_id][year, material] = {
            "installed_usd": installed, "material_usd": material_cost, "labor_usd": labor_cost,
        }
        if material == "OFFICIAL_METAL" and tile_proxy:
            prices[asset_id][year, "OFFICIAL_TILE"] = {
                key: value * TEMPORARY_TILE_COST_MULTIPLIER for key, value in prices[asset_id][year, material].items()
            }
    paths = _source_paths(CADENCE_ROOT)
    for name in REMOVAL_SOURCES:
        if file_sha256(paths[name]) != metadata.get("source_checksums", {}).get(name):
            raise ValueError(f"Removal source {name} differs from the parent; rerun Alternative Analysis")
    event_state = costs.select(
        "asset_id", "year", pl.col("official_material_id").alias("scenario_id"),
        pl.col("official_material_id").alias("removed_material_id"),
        pl.lit(True).alias("installation_event"),
    )
    mass = build_material_mass_lookup(paths["material_mass"], paths["mapping"], paths["class_map"])
    removal_frame = build_scenario_event_costs(
        event_state, assets, mass, config, paths["disposal"], paths["carbon"],
        paths["scghg"], paths["mapping"], paths["class_map"],
    )
    for row in removal_frame.iter_rows(named=True):
        removals[row["asset_id"]][int(row["year"]), row["removed_material_id"]] = {
            "disposal_usd": float(row["event_disposal_cost_usd"]) if CostStream.DISPOSAL in config.enabled_cost_streams else 0.0,
            "carbon_usd": float(row["event_carbon_cost_usd"]) if CostStream.CARBON in config.enabled_cost_streams else 0.0,
        }

    hazards = {(row["asset_id"], int(row["year"])): row for row in baseline.iter_rows(named=True)}

    source_materials = ["OFFICIAL_ASPHALT", "OFFICIAL_METAL"] if tile_proxy else list(MATERIALS)
    keys = baseline.select("climate_zone", "terrain_id").unique().join(
        pl.DataFrame({"lookup_roof_age": list(range(1, 31))}), how="cross",
    ).join(pl.DataFrame({"source_material_id": source_materials}), how="cross")
    curves = load_fragility_curves(FRAGILITY_ROOT, keys)
    curve_lookup = {
        key: (frame["wind_speed_mph"].to_numpy(), frame["building_loss_ratio"].to_numpy())
        for key, frame in curves.partition_by(CURVE_KEYS, as_dict=True).items()
    }

    @lru_cache(maxsize=50000)
    def damage_ratio(zone: str, terrain: int, proxy: str, age: int, gusts: tuple[float, ...]) -> float:
        winds, ratios = curve_lookup[zone, age, proxy, terrain]
        damage, _, _ = interpolate_return_period_damage(
            list(gusts), winds, ratios
        )
        return float(integrate_damage_matrix(damage.reshape(1, -1))[0])

    def risk(asset_id: str, year: int, material: str, age: int) -> tuple[float, float]:
        source_year = min(year, config.end_year)
        hazard = hazards[asset_id, source_year]
        proxy = "OFFICIAL_METAL" if tile_proxy and material == "OFFICIAL_TILE" else material
        expected = damage_ratio(
            str(hazard["climate_zone"]), int(hazard["terrain_id"]), proxy, min(age + 1, 30),
            tuple(hazard[column] for column in SCALED_GUST_COLUMNS),
        )
        return prices[asset_id][source_year, material]["installed_usd"] * expected, 0.0

    for asset in assets.iter_rows(named=True):
        current = asset["current_roof_eul_years"]
        lives[asset["asset_id"]]["initial_eul"] = (floor(float(current) + 0.5) if current is not None
                                                else lives[asset["asset_id"]][asset["official_current_material_id"]])
    if snapshot_root is not None:
        snapshot_root.mkdir()
        for name, frame in (
            ("assets", assets), ("hazard", baseline), ("curves", curves),
            ("option_costs", costs), ("removal_costs", removal_frame),
            ("service_lives", pl.DataFrame([{"asset_id": key, **value} for key, value in lives.items()])),
        ):
            frame.write_parquet(snapshot_root / f"{name}.parquet")
    return assets, prices, removals, lives, risk