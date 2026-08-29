"""Immutable orchestration for annual roof alternative analysis."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import polars as pl

from cadence.economics.alternative_analysis import (
    build_annual_alternative_economics,
    build_annual_scenario_state,
)
from cadence.economics.contracts import EconomicsRunConfig
from cadence.economics.externalities import build_scenario_event_costs
from cadence.economics.materials import (
    build_material_mass_lookup,
    build_physical_service_life_lookup,
)
from cadence.economics.pipeline import _sha256, run_economics_pipeline
from cadence.economics.reporting import write_alternative_analysis_report
from cadence.economics.temporary_policies import (
    TEMPORARY_TILE_COST_MULTIPLIER,
    TEMPORARY_TILE_POLICY_ID,
)
from cadence.reference_data.climate_delta import resolve_climate_scale_factors
from cadence.reference_data.year1_damage import _fragility_identity
from cadence.vulnerability.annual_damage import GUST_COLUMNS, build_annual_scenario_damage

ALTERNATIVE_ANALYSIS_SCHEMA_VERSION = "v0.4.0"


def run_alternative_analysis_pipeline(
    assets: pl.DataFrame,
    config: EconomicsRunConfig,
    asset_scoped_damage: pl.DataFrame,
    repository_root: Path,
    fragility_root: Path,
    output_root: Path,
    annual_loss_of_use: Optional[pl.DataFrame] = None,
    climate_delta_path: Optional[Path] = None,
) -> Dict[str, object]:
    """Run and publish the four-scenario roof lifecycle analysis."""
    paths = _source_paths(repository_root, climate_delta_path)
    service_lives = build_physical_service_life_lookup(
        paths["material_mass"], paths["mapping"], paths["class_map"]
    )
    service_lives = _apply_temporary_tile_service_life_policy(service_lives)
    annual_state = build_annual_scenario_state(assets, service_lives, config)
    annual_state = annual_state.with_columns(
        (pl.col("scenario_id") == "NEW_TILE").alias(
            "temporary_tile_metal_proxy_applied"
        )
    )
    fragility_keys = _fragility_keys(annual_state, asset_scoped_damage)
    fragility_identity = _fragility_identity(fragility_keys, fragility_root)
    climate_factors = resolve_climate_scale_factors(
        paths["climate_delta"],
        _climate_factor_keys(annual_state, asset_scoped_damage),
    )
    source_checksums = {
        name: _sha256(path) for name, path in paths.items()
    }
    run_id = _run_id(
        assets,
        config,
        asset_scoped_damage,
        annual_loss_of_use,
        source_checksums,
        fragility_identity,
    )
    run_root = (
        output_root
        / f"schema_version={ALTERNATIVE_ANALYSIS_SCHEMA_VERSION}"
        / f"run_id={run_id}"
    )
    manifest_path = run_root / "run_metadata.json"
    if manifest_path.exists():
        cached = json.loads(manifest_path.read_text(encoding="utf-8"))
        cached["cache_hit"] = True
        return cached

    annual_hazard_economics = annual_loss_of_use
    economics_manifest = run_economics_pipeline(
        assets,
        config,
        repository_root,
        output_root / "economics_reference",
        annual_hazard_economics=annual_hazard_economics,
    )
    annual_option_costs = pl.read_parquet(
        str(Path(economics_manifest["annual_costs_path"]) / "year=*" / "*.parquet"),
        hive_partitioning=False,
    )
    annual_option_costs = _apply_temporary_tile_cost_policy(annual_option_costs)
    damage_state = annual_state.with_columns(
        pl.when(pl.col("scenario_id") == "NEW_TILE")
        .then(pl.lit("OFFICIAL_METAL"))
        .otherwise(pl.col("scenario_material_id"))
        .alias("scenario_material_id")
    )
    annual_damage = build_annual_scenario_damage(
        damage_state, asset_scoped_damage, fragility_root, climate_factors
    ).with_columns(
        pl.when(pl.col("scenario_id") == "NEW_TILE")
        .then(pl.lit("OFFICIAL_TILE"))
        .otherwise(pl.col("scenario_material_id"))
        .alias("scenario_material_id")
    )
    material_mass = build_material_mass_lookup(
        paths["material_mass"], paths["mapping"], paths["class_map"]
    )
    event_costs = build_scenario_event_costs(
        annual_state,
        assets,
        material_mass,
        config,
        paths["disposal"],
        paths["carbon"],
        paths["scghg"],
        paths["mapping"],
        paths["class_map"],
    )
    annual_analysis = build_annual_alternative_economics(
        annual_state,
        annual_damage,
        annual_option_costs,
        config,
        event_costs=event_costs,
    )
    summary = _build_summary(annual_analysis)

    _write_partitioned(annual_state, run_root / "annual_scenario_state")
    _write_partitioned(annual_damage, run_root / "annual_scenario_damage")
    _write_partitioned(annual_analysis, run_root / "annual_alternative_analysis")
    summary_path = run_root / "alternative_summary.parquet"
    summary.write_parquet(summary_path)
    report_path = run_root / "alternative_analysis_report.html"
    write_alternative_analysis_report(annual_analysis, report_path)

    manifest = {
        "run_id": run_id,
        "schema_version": ALTERNATIVE_ANALYSIS_SCHEMA_VERSION,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "run_config": config.model_dump(mode="json"),
        "source_checksums": source_checksums,
        "fragility_identity": fragility_identity,
        "economics_reference_run_id": economics_manifest["run_id"],
        "asset_count": assets.height,
        "scenario_count_per_asset_year": 4,
        "annual_state_row_count": annual_state.height,
        "annual_damage_row_count": annual_damage.height,
        "annual_analysis_row_count": annual_analysis.height,
        "summary_row_count": summary.height,
        "climate_scaling_enabled": True,
        "climate_delta_path": str(paths["climate_delta"].resolve()),
        "climate_delta_checksum": source_checksums["climate_delta"],
        "climate_delta_source_years": [2025, 2050],
        "climate_scale_interpretation": "dimensionless wind-speed multiplier",
        "climate_scale_pre_2025_rule": "factor_1.0",
        "climate_scale_post_2050_rule": "linear_factor_slope_from_2040_to_2050",
        "age_30_fragility_cap": True,
        "eul_precedence": "asset_current_roof_eul_then_official_physical_default",
        "eul_rounding": "nearest_whole_year_half_away_from_zero",
        "cash_flow_timing": "start_of_year_installation_before_damage",
        "dollar_basis": "real_2026_usd",
        "temporary_tile_policy": {
            "policy_id": TEMPORARY_TILE_POLICY_ID,
            "lifecycle_and_vulnerability_source": "NEW_METAL",
            "installed_cost_source": "OFFICIAL_METAL",
            "installed_cost_multiplier": TEMPORARY_TILE_COST_MULTIPLIER,
            "scenario_identity_retained": "NEW_TILE/OFFICIAL_TILE",
        },
        "cache_hit": False,
        "annual_state_path": str(run_root / "annual_scenario_state"),
        "annual_damage_path": str(run_root / "annual_scenario_damage"),
        "annual_analysis_path": str(run_root / "annual_alternative_analysis"),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest


def _build_summary(annual_analysis: pl.DataFrame) -> pl.DataFrame:
    alternatives = annual_analysis.filter(pl.col("scenario_role") == "new_alternative")
    return (
        alternatives.sort(["asset_id", "scenario_id", "year"])
        .group_by("asset_id", "scenario_id", "scenario_material_id")
        .agg(
            pl.col("year").max().alias("through_year"),
            pl.col("cumulative_avoided_damage_usd").last(),
            pl.col("cumulative_discounted_avoided_damage_usd").last(),
            pl.col("cumulative_net_benefit_usd").last(),
            pl.col("net_present_value_usd").last(),
            pl.col("burnout_replacement_event").sum().alias("burnout_replacement_count"),
            pl.col("active_cost_source").first(),
            pl.col("active_cost_fallback_applied").any(),
            pl.col("repair_cost_incomplete").any(),
            pl.col("climate_risk_total_incomplete").any(),
            pl.col("event_cost_incomplete").any(),
        )
        .sort(["asset_id", "scenario_id"])
    )


def _fragility_keys(
    annual_state: pl.DataFrame, asset_scoped_damage: pl.DataFrame
) -> pl.DataFrame:
    required = ["asset_id", "climate_zone", "terrain_id", "wind_grid_id", *GUST_COLUMNS]
    missing = sorted(set(required) - set(asset_scoped_damage.columns))
    if missing:
        raise ValueError(f"asset_scoped_damage is missing required columns: {missing}")
    hazard = asset_scoped_damage.select(required).unique()
    if hazard.group_by("asset_id").len().filter(pl.col("len") != 1).height:
        raise ValueError("asset-scoped damage contains inconsistent hazard fields")
    return annual_state.select("asset_id", "lookup_roof_age").unique().join(
        hazard, on="asset_id", how="left", validate="m:1"
    )


def _climate_factor_keys(
    annual_state: pl.DataFrame, asset_scoped_damage: pl.DataFrame
) -> pl.DataFrame:
    asset_grids = asset_scoped_damage.select("asset_id", "wind_grid_id").unique()
    if asset_grids.group_by("asset_id").len().filter(pl.col("len") != 1).height:
        raise ValueError("asset-scoped damage contains inconsistent wind grid IDs")
    return (
        annual_state.select("asset_id", "year")
        .unique()
        .join(asset_grids, on="asset_id", how="left", validate="m:1")
        .select("wind_grid_id", "year")
        .unique()
    )


def _source_paths(
    repository_root: Path, climate_delta_path: Optional[Path] = None
) -> Dict[str, Path]:
    mapping_root = repository_root / "Data_Catalogs" / "Mapping"
    return {
        "material_mass": repository_root / "Data" / "Material_Mass" / "roofing_lbs.csv",
        "disposal": repository_root / "Data" / "Disposal" / "EREF_2024_Tipping_Fees_Parsed.csv",
        "carbon": repository_root / "Data" / "Carbon" / "roofing_eol_emission_factors.csv",
        "scghg": repository_root / "Data" / "Carbon" / "table_a5_1_scghg_unrounded_2020_2080.csv",
        "mapping": mapping_root / "master_mapping_reference_draft.csv",
        "class_map": mapping_root / "official_material_class_map_v1.csv",
        "consolidation_rules": mapping_root / "material_consolidation_rules_v1.csv",
        "climate_delta": (
            climate_delta_path
            if climate_delta_path is not None
            else repository_root / "Data" / "Climate_Delta" / "wind_climate_scaling.parquet"
        ),
    }


def _run_id(
    assets: pl.DataFrame,
    config: EconomicsRunConfig,
    damage: pl.DataFrame,
    loss_of_use: Optional[pl.DataFrame],
    source_checksums: Dict[str, str],
    fragility_identity: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(config.model_dump_json().encode("utf-8"))
    for frame in (assets, damage, loss_of_use):
        if frame is not None:
            digest.update(frame.sort(frame.columns).hash_rows().to_numpy().tobytes())
    digest.update(json.dumps(source_checksums, sort_keys=True).encode("utf-8"))
    digest.update(fragility_identity.encode("utf-8"))
    digest.update(TEMPORARY_TILE_POLICY_ID.encode("utf-8"))
    return digest.hexdigest()[:24]


def _apply_temporary_tile_service_life_policy(
    service_lives: pl.DataFrame,
) -> pl.DataFrame:
    """Temporarily give Tile the Metal physical service-life values."""
    metal = service_lives.filter(
        pl.col("official_material_id") == "OFFICIAL_METAL"
    )
    if metal.height != 1:
        raise ValueError("temporary Tile policy requires exactly one Metal service life")
    tile = metal.with_columns(
        pl.lit("OFFICIAL_TILE").alias("official_material_id"),
        pl.lit(TEMPORARY_TILE_POLICY_ID).alias("mapping_version"),
    )
    return pl.concat(
        [
            service_lives.filter(
                pl.col("official_material_id") != "OFFICIAL_TILE"
            ),
            tile,
        ],
        how="vertical",
    ).sort("official_material_id")


def _apply_temporary_tile_cost_policy(
    annual_option_costs: pl.DataFrame,
) -> pl.DataFrame:
    """Temporarily derive Tile annual option costs from Metal at 1.2x."""
    metal = annual_option_costs.filter(
        pl.col("official_material_id") == "OFFICIAL_METAL"
    )
    expected = annual_option_costs.select("asset_id", "year").unique().height
    if metal.height != expected:
        raise ValueError(
            "temporary Tile policy requires one Metal option cost per asset-year"
        )
    expressions = [
        pl.lit("OFFICIAL_TILE").alias("official_material_id"),
        (pl.col("installed_capex_usd") * TEMPORARY_TILE_COST_MULTIPLIER).alias(
            "installed_capex_usd"
        ),
        pl.lit(TEMPORARY_TILE_POLICY_ID).alias("operational_cost_source"),
        pl.lit(False).alias("operational_cost_fallback_applied"),
    ]
    tile = metal.with_columns(*expressions)
    return pl.concat(
        [
            annual_option_costs.filter(
                pl.col("official_material_id") != "OFFICIAL_TILE"
            ),
            tile,
        ],
        how="vertical",
    ).sort(["asset_id", "year", "official_material_id"])


def _write_partitioned(frame: pl.DataFrame, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for key, partition in frame.partition_by("year", as_dict=True).items():
        year = key[0] if isinstance(key, tuple) else key
        year_root = root / f"year={year}"
        year_root.mkdir()
        partition.write_parquet(year_root / "part-00000.parquet")


def _write_json_atomic(path: Path, value: Dict[str, object]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)