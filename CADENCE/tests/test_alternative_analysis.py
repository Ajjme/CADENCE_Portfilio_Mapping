import polars as pl
import pytest

from cadence.economics.alternative_analysis import (
    build_annual_alternative_economics,
    build_annual_scenario_state,
)
from cadence.economics.contracts import EconomicsRunConfig


def _config() -> EconomicsRunConfig:
    return EconomicsRunConfig.model_validate(
        {
            "installed_cost_overrides": {
                material: {
                    "installed_usd_per_sqft": 10.0,
                    "material_share": 0.6,
                    "labor_share": 0.4,
                }
                for material in (
                    "OFFICIAL_ASPHALT",
                    "OFFICIAL_METAL",
                    "OFFICIAL_TILE",
                )
            },
            "default_roof_shape": "gable",
            "default_roof_deck_attachment": "8d_6in_12in",
            "default_roof_wall_connection": "strap",
        }
    )


def _service_lives() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "official_material_id": [
                "OFFICIAL_ASPHALT",
                "OFFICIAL_METAL",
                "OFFICIAL_TILE",
            ],
            "raw_physical_eul_years": [24.17, 55.0, 60.0],
            "applied_physical_eul_years": [24, 55, 60],
            "mapping_version": ["v1.0.0"] * 3,
        }
    )


def test_builds_four_scenarios_for_every_year_and_keeps_same_material_distinct() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "official_current_material_id": ["OFFICIAL_ASPHALT"],
            "input_roof_age": [10],
        }
    )

    result = build_annual_scenario_state(assets, _service_lives(), _config())
    first_year = result.filter(pl.col("year") == 2026)

    assert result.height == 100
    assert first_year["scenario_id"].n_unique() == 4
    asphalt = first_year.filter(
        pl.col("scenario_material_id") == "OFFICIAL_ASPHALT"
    ).sort("scenario_id")
    assert asphalt.height == 2
    assert set(asphalt["roof_age_years"].to_list()) == {0, 10}
    assert set(asphalt["lookup_roof_age"].to_list()) == {1, 11}
    new_asphalt = first_year.filter(pl.col("scenario_id") == "NEW_ASPHALT").row(
        0, named=True
    )
    assert new_asphalt["removed_material_id"] == "OFFICIAL_ASPHALT"


def test_uses_user_eul_and_replaces_burned_out_baseline_at_start_of_year() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "official_current_material_id": ["OFFICIAL_ASPHALT"],
            "input_roof_age": [2],
            "current_roof_eul_years": [3.0],
        }
    )

    result = build_annual_scenario_state(assets, _service_lives(), _config())
    baseline = result.filter(pl.col("scenario_id") == "BASELINE_CURRENT")
    year_2027 = baseline.filter(pl.col("year") == 2027).row(0, named=True)

    assert baseline.row(0, named=True)["eul_source"] == "asset_current_roof_eul"
    assert year_2027["burnout_replacement_event"] is True
    assert year_2027["roof_age_years"] == 0
    assert year_2027["lookup_roof_age"] == 1
    assert year_2027["install_sequence"] == 1
    assert year_2027["applied_eul_years"] == 24
    assert year_2027["eul_source"] == "official_class_physical_default"


def test_caps_fragility_lookup_age_without_changing_chronological_age() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "official_current_material_id": ["OFFICIAL_METAL"],
            "input_roof_age": [35],
        }
    )

    result = build_annual_scenario_state(assets, _service_lives(), _config())
    baseline = result.filter(
        (pl.col("scenario_id") == "BASELINE_CURRENT") & (pl.col("year") == 2026)
    ).row(0, named=True)

    assert baseline["roof_age_years"] == 35
    assert baseline["lookup_roof_age"] == 30
    assert baseline["age_capped"] is True


def test_calculates_repair_avoided_damage_and_discounted_lifecycle_benefit() -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1"] * 8,
            "year": [2026] * 4 + [2027] * 4,
            "scenario_id": [
                "BASELINE_CURRENT",
                "NEW_ASPHALT",
                "NEW_METAL",
                "NEW_TILE",
            ]
            * 2,
            "scenario_role": (["installed_baseline"] + ["new_alternative"] * 3)
            * 2,
            "scenario_material_id": [
                "OFFICIAL_ASPHALT",
                "OFFICIAL_ASPHALT",
                "OFFICIAL_METAL",
                "OFFICIAL_TILE",
            ]
            * 2,
            "installation_event": [False, True, True, True] + [False] * 4,
        }
    )
    damage = state.select("asset_id", "year", "scenario_id").with_columns(
        pl.when(pl.col("scenario_id") == "BASELINE_CURRENT")
        .then(pl.lit(0.01))
        .otherwise(pl.lit(0.005))
        .alias("expected_damage_ratio")
    )
    options = pl.DataFrame(
        {
            "asset_id": ["A-1"] * 6,
            "year": [2026] * 3 + [2027] * 3,
            "official_material_id": [
                "OFFICIAL_ASPHALT",
                "OFFICIAL_METAL",
                "OFFICIAL_TILE",
            ]
            * 2,
            "roof_area_sqft": [10_000.0] * 6,
            "installed_capex_usd": [100_000.0, 120_000.0, 140_000.0] * 2,
            "operational_cost_source": ["source_computed_material_labor"] * 6,
            "operational_cost_fallback_applied": [False] * 6,
        }
    )

    result = build_annual_alternative_economics(
        state, damage, options, _config()
    )
    baseline_2026 = result.filter(
        (pl.col("year") == 2026) & (pl.col("scenario_id") == "BASELINE_CURRENT")
    ).row(0, named=True)
    new_asphalt_2026 = result.filter(
        (pl.col("year") == 2026) & (pl.col("scenario_id") == "NEW_ASPHALT")
    ).row(0, named=True)
    new_asphalt_2027 = result.filter(
        (pl.col("year") == 2027) & (pl.col("scenario_id") == "NEW_ASPHALT")
    ).row(0, named=True)

    assert baseline_2026["annual_repair_cost_usd"] == 1_000.0
    assert new_asphalt_2026["active_installed_capex_usd"] == 100_000.0
    assert new_asphalt_2026["annual_repair_cost_usd"] == 500.0
    assert new_asphalt_2026["annual_avoided_damage_usd"] == 500.0
    assert new_asphalt_2026["annual_net_benefit_usd"] == -99_500.0
    assert new_asphalt_2026["discount_factor"] == 1.0
    assert new_asphalt_2027["discount_factor"] == pytest.approx(1 / 1.02)
    assert new_asphalt_2027["net_present_value_usd"] == pytest.approx(
        -99_500.0 + 500.0 / 1.02
    )


def test_keeps_repair_chartable_when_enabled_loss_of_use_is_missing() -> None:
    config = _config().model_copy(
        update={"enabled_cost_streams": frozenset(["material", "labor", "loss_of_use"])}
    )
    state = pl.DataFrame(
        {
            "asset_id": ["A-1"] * 4,
            "year": [2026] * 4,
            "scenario_id": [
                "BASELINE_CURRENT",
                "NEW_ASPHALT",
                "NEW_METAL",
                "NEW_TILE",
            ],
            "scenario_role": ["installed_baseline"] + ["new_alternative"] * 3,
            "scenario_material_id": [
                "OFFICIAL_ASPHALT",
                "OFFICIAL_ASPHALT",
                "OFFICIAL_METAL",
                "OFFICIAL_TILE",
            ],
            "installation_event": [False, True, True, True],
        }
    )
    damage = state.select("asset_id", "year", "scenario_id").with_columns(
        pl.lit(0.01).alias("expected_damage_ratio")
    )
    options = pl.DataFrame(
        {
            "asset_id": ["A-1"] * 3,
            "year": [2026] * 3,
            "official_material_id": [
                "OFFICIAL_ASPHALT",
                "OFFICIAL_METAL",
                "OFFICIAL_TILE",
            ],
            "roof_area_sqft": [10_000.0] * 3,
            "installed_capex_usd": [100_000.0] * 3,
            "operational_cost_source": ["source_computed_material_labor"] * 3,
            "operational_cost_fallback_applied": [False] * 3,
        }
    )

    result = build_annual_alternative_economics(state, damage, options, config)

    assert result["annual_repair_cost_usd"].null_count() == 0
    assert result["annual_climate_risk_cost_usd"].null_count() == 4
    assert result["climate_risk_total_incomplete"].to_list() == [True] * 4