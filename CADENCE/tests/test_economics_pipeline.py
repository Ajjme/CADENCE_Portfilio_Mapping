from pathlib import Path

import polars as pl
import pytest

from cadence.economics.contracts import EconomicsRunConfig
from cadence.economics.pipeline import run_economics_pipeline


@pytest.mark.parametrize(("start_year", "end_year"), [(2026, 2050), (2030, 2031)])
def test_runs_repeatable_repository_economics_pipeline(
    tmp_path: Path, start_year: int, end_year: int
) -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "official_current_material_id": ["OFFICIAL_ASPHALT"],
            "roof_area_sqft": [1_000.0],
            "zip_code": ["77001"],
            "cbsa_code": ["26420"],
            "state_code": ["TX"],
            "county_fips": ["48201"],
            "labor_market_id": ["0010180"],
            "roof_shape": [None],
            "roof_deck_attachment": [None],
            "roof_wall_connection": [None],
        }
    )
    config = EconomicsRunConfig.model_validate(
        {
            "enabled_cost_streams": [
                "material", "labor", "disposal", "carbon", "loss_of_use"
            ],
            "installed_cost_overrides": {
                "OFFICIAL_ASPHALT": {
                    "installed_usd_per_sqft": 10.0,
                    "material_share": 0.6,
                    "labor_share": 0.4,
                },
                "OFFICIAL_METAL": {
                    "installed_usd_per_sqft": 15.0,
                    "material_share": 0.7,
                    "labor_share": 0.3,
                },
                "OFFICIAL_TILE": {
                    "installed_usd_per_sqft": 20.0,
                    "material_share": 0.5,
                    "labor_share": 0.5,
                },
            },
            "default_roof_shape": "flat",
            "default_roof_deck_attachment": "6d_6in_12in",
            "default_roof_wall_connection": "strap",
        }
    )
    config = EconomicsRunConfig.model_validate(
        {**config.model_dump(mode="json"), "start_year": start_year, "end_year": end_year}
    )
    hazard = pl.DataFrame(
        {
            "asset_id": ["A-1"] * 75,
            "year": [year for year in range(2026, 2051) for _ in range(3)],
            "official_material_id": [
                material
                for _ in range(25)
                for material in (
                    "OFFICIAL_ASPHALT",
                    "OFFICIAL_METAL",
                    "OFFICIAL_TILE",
                )
            ],
            "expected_damage_ratio": [0.1] * 75,
            "expected_loss_of_use_days": [2.0] * 75,
        }
    )

    manifest = run_economics_pipeline(
        assets, config, Path.cwd(), tmp_path, annual_hazard_economics=hazard
    )
    repeated = run_economics_pipeline(
        assets, config, Path.cwd(), tmp_path, annual_hazard_economics=hazard
    )

    year_count = end_year - start_year + 1
    assert manifest["annual_option_row_count"] == 3 * year_count
    assert manifest["operational_check_row_count"] == year_count
    assert manifest["run_config"]["start_year"] == start_year
    assert manifest["run_config"]["end_year"] == end_year
    assert manifest["run_id"] == repeated["run_id"]
    if start_year == 2030:
        changed_rate = EconomicsRunConfig.model_validate({
            **config.model_dump(mode="json"), "real_discount_rate": 0.04,
        })
        other = run_economics_pipeline(
            assets, changed_rate, Path.cwd(), tmp_path, annual_hazard_economics=hazard
        )
        assert other["run_id"] != manifest["run_id"]
        assert other["run_config"]["real_discount_rate"] == 0.04
    run_root = (
        tmp_path
        / "schema_version=v0.3.0"
        / f"run_id={manifest['run_id']}"
    )
    assert len(list((run_root / "annual_roof_option_costs").glob("year=*"))) == year_count
    assert (run_root / "operational_value_checks.parquet").exists()
    assert (run_root / "run_metadata.json").exists()

    surge_config = config.model_copy(update={"demand_surge": True})
    surged_manifest = run_economics_pipeline(
        assets, surge_config, Path.cwd(), tmp_path, annual_hazard_economics=hazard
    )
    assert surged_manifest["run_id"] != manifest["run_id"]
    assert surged_manifest["run_config"]["demand_surge"] is True
    assert "labor_base_wide" in surged_manifest["source_checksums"]

    def annual_costs(run_manifest):
        return pl.read_parquet(
            str(Path(run_manifest["annual_costs_path"]) / f"year={end_year}" / "*.parquet"),
            hive_partitioning=False,
        )

    regular = annual_costs(manifest)
    surged = annual_costs(surged_manifest)
    source = pl.col("operational_cost_source") == "source_computed_material_labor"
    fallback = pl.col("operational_cost_source") == "class_installed_override_fallback"
    assert surged.filter(source)["source_labor_usd_per_sqft"].sum() > regular.filter(source)["source_labor_usd_per_sqft"].sum()
    assert surged.filter(fallback)["installed_capex_usd"].to_list() == pytest.approx(
        regular.filter(fallback)["installed_capex_usd"].to_list()
    )