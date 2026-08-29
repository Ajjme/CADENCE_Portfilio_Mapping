from pathlib import Path

import polars as pl
import pytest

from cadence.economics.alternative_pipeline import (
    TEMPORARY_TILE_COST_MULTIPLIER,
    TEMPORARY_TILE_POLICY_ID,
    _source_paths,
    run_alternative_analysis_pipeline,
)
from cadence.economics.contracts import EconomicsRunConfig
from cadence.vulnerability.annual_damage import GUST_COLUMNS


def _config() -> EconomicsRunConfig:
    return EconomicsRunConfig.model_validate(
        {
            "installed_cost_overrides": {
                material: {
                    "installed_usd_per_sqft": cost,
                    "material_share": 0.6,
                    "labor_share": 0.4,
                }
                for material, cost in (
                    ("OFFICIAL_ASPHALT", 8.0),
                    ("OFFICIAL_METAL", 12.0),
                    ("OFFICIAL_TILE", 14.0),
                )
            },
            "default_roof_shape": "flat",
            "default_roof_deck_attachment": "6d_6in_12in",
            "default_roof_wall_connection": "strap",
        }
    )


def test_uses_repository_climate_scaling_as_default() -> None:
    repository_root = Path("repository")

    paths = _source_paths(repository_root)

    assert paths["climate_delta"] == (
        repository_root / "Data" / "Climate_Delta" / "wind_climate_scaling.parquet"
    )


def test_publishes_repeatable_alternative_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "official_current_material_id": ["OFFICIAL_ASPHALT"],
            "input_roof_age": [10],
            "roof_area_sqft": [1_000.0],
            "state_code": ["SC"],
        }
    )
    hazard_rows = {
        "asset_id": ["A-1"] * 3,
        "wind_grid_id": [1] * 3,
        "climate_zone": ["3A"] * 3,
        "terrain_id": [3] * 3,
    }
    hazard_rows.update({column: [75.0] * 3 for column in GUST_COLUMNS})
    hazard = pl.DataFrame(hazard_rows)
    climate_path = tmp_path / "climate.parquet"
    climate_columns = {"lat_idx": [0], "lon_idx": [1]}
    climate_columns.update(
        {f"scale_{year}": [1.0 + (year - 2025) * 0.001] for year in range(2025, 2051)}
    )
    pl.DataFrame(climate_columns).write_parquet(climate_path)

    def fake_economics(*args, **kwargs):
        root = tmp_path / "reference_costs"
        for year in range(2026, 2051):
            year_root = root / f"year={year}"
            year_root.mkdir(parents=True, exist_ok=True)
            pl.DataFrame(
                {
                    "asset_id": ["A-1"] * 3,
                    "year": [year] * 3,
                    "official_material_id": [
                        "OFFICIAL_ASPHALT",
                        "OFFICIAL_METAL",
                        "OFFICIAL_TILE",
                    ],
                    "roof_area_sqft": [1_000.0] * 3,
                    "installed_capex_usd": [12_000.0, 12_000.0, 14_000.0],
                    "operational_cost_source": [
                        "source_computed_material_labor",
                        "source_computed_material_labor",
                        "class_installed_override_fallback",
                    ],
                    "operational_cost_fallback_applied": [False, False, True],
                }
            ).write_parquet(year_root / "part.parquet")
        return {"run_id": "economics-test", "annual_costs_path": str(root)}

    def fake_damage(state, _, __, factors):
        assert factors.height == 25
        return state.join(
            factors.select("year", "climate_scale_factor"), on="year", validate="m:1"
        ).with_columns(pl.lit(0.01).alias("expected_damage_ratio"))

    monkeypatch.setattr(
        "cadence.economics.alternative_pipeline.run_economics_pipeline",
        fake_economics,
    )
    monkeypatch.setattr(
        "cadence.economics.alternative_pipeline.build_annual_scenario_damage",
        fake_damage,
    )
    monkeypatch.setattr(
        "cadence.economics.alternative_pipeline._fragility_identity",
        lambda *_: "fragility-test",
    )

    manifest = run_alternative_analysis_pipeline(
        assets,
        _config(),
        hazard,
        Path.cwd(),
        Path("unused"),
        tmp_path / "analysis",
        climate_delta_path=climate_path,
    )
    repeated = run_alternative_analysis_pipeline(
        assets,
        _config(),
        hazard,
        Path.cwd(),
        Path("unused"),
        tmp_path / "analysis",
        climate_delta_path=climate_path,
    )

    assert manifest["annual_analysis_row_count"] == 100
    assert manifest["summary_row_count"] == 3
    assert manifest["climate_scaling_enabled"] is True
    assert manifest["climate_delta_checksum"] == manifest["source_checksums"]["climate_delta"]
    assert manifest["temporary_tile_policy"] == {
        "policy_id": TEMPORARY_TILE_POLICY_ID,
        "lifecycle_and_vulnerability_source": "NEW_METAL",
        "installed_cost_source": "OFFICIAL_METAL",
        "installed_cost_multiplier": TEMPORARY_TILE_COST_MULTIPLIER,
        "scenario_identity_retained": "NEW_TILE/OFFICIAL_TILE",
    }
    assert repeated["cache_hit"] is True
    run_root = Path(manifest["annual_analysis_path"]).parent
    assert len(list((run_root / "annual_alternative_analysis").glob("year=*"))) == 25
    assert (run_root / "alternative_summary.parquet").exists()
    assert (run_root / "alternative_analysis_report.html").exists()
    assert (run_root / "run_metadata.json").exists()
    state = pl.read_parquet(
        run_root / "annual_scenario_state" / "year=2026" / "part-00000.parquet"
    )
    metal_state = state.filter(pl.col("scenario_id") == "NEW_METAL").row(
        0, named=True
    )
    tile_state = state.filter(pl.col("scenario_id") == "NEW_TILE").row(
        0, named=True
    )
    for column in (
        "roof_age_years",
        "raw_physical_eul_years",
        "applied_physical_eul_years",
        "applied_eul_years",
        "installation_event",
        "remaining_useful_life_years",
    ):
        assert tile_state[column] == metal_state[column]
    assert tile_state["scenario_material_id"] == "OFFICIAL_TILE"
    assert tile_state["temporary_tile_metal_proxy_applied"] is True

    damage = pl.read_parquet(
        run_root / "annual_scenario_damage" / "year=2026" / "part-00000.parquet"
    )
    metal_damage = damage.filter(pl.col("scenario_id") == "NEW_METAL").row(
        0, named=True
    )
    tile_damage = damage.filter(pl.col("scenario_id") == "NEW_TILE").row(
        0, named=True
    )
    assert tile_damage["scenario_material_id"] == "OFFICIAL_TILE"
    assert tile_damage["expected_damage_ratio"] == metal_damage["expected_damage_ratio"]

    annual = pl.read_parquet(
        run_root / "annual_alternative_analysis" / "year=2026" / "part-00000.parquet"
    )
    metal_annual = annual.filter(pl.col("scenario_id") == "NEW_METAL").row(
        0, named=True
    )
    tile_annual = annual.filter(pl.col("scenario_id") == "NEW_TILE").row(
        0, named=True
    )
    assert tile_annual["active_installed_capex_usd"] == pytest.approx(
        metal_annual["active_installed_capex_usd"] * TEMPORARY_TILE_COST_MULTIPLIER
    )
    assert tile_annual["annual_repair_cost_usd"] == pytest.approx(
        metal_annual["annual_repair_cost_usd"] * TEMPORARY_TILE_COST_MULTIPLIER
    )
    summary = pl.read_parquet(run_root / "alternative_summary.parquet")
    tile = summary.filter(pl.col("scenario_id") == "NEW_TILE").row(0, named=True)
    assert tile["active_cost_source"] == TEMPORARY_TILE_POLICY_ID
    assert tile["active_cost_fallback_applied"] is False