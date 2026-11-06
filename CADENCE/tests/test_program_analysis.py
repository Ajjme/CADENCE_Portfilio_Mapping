from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from cadence.economics.alternative_analysis import build_annual_scenario_state
from cadence.economics.contracts import CostStream
from cadence.program.analysis import evaluate, summarize
from cadence.program.contracts import COMPONENTS, ProgramInputs, TARGETS
from cadence.program.pipeline import load_program, load_snapshot, publish_program
from cadence.reference_data.fragility import (
    CURVE_AGGREGATION_METHOD, FRAGILITY_MAPPING_VERSION, MATERIAL_PROXY_IDS,
)
from cadence.vulnerability.annual_damage import GUST_COLUMNS
from test_alternative_analysis import _config, _service_lives


@pytest.fixture
def inputs():
    config = _config().model_copy(update={"end_year": 2028})
    assets = pl.DataFrame({
        "asset_id": ["A"], "official_current_material_id": ["OFFICIAL_ASPHALT"],
        "input_roof_age": [2], "current_roof_eul_years": [3.0],
        "roof_area_sqft": [1000.0], "state_code": ["SC"],
    })
    lives = _service_lives()
    states = pl.concat([
        build_annual_scenario_state(assets, lives, config, installation_year=y)
        .with_columns(pl.lit(y).alias("candidate_year"))
        for y in range(2026, 2029)
    ])
    costs = pl.DataFrame([
        {"asset_id": "A", "year": y, "official_material_id": m,
         "roof_area_sqft": 1000.0, "installed_capex_usd": cost,
         "operational_cost_source": "fixture", "operational_cost_fallback_applied": False}
        for y in range(2026, 2029)
        for m, cost in zip(MATERIAL_PROXY_IDS, (12000.0, 20000.0, 24000.0))
    ])
    removals = costs.select("asset_id", "year", "official_material_id").with_columns(
        pl.lit(100.0).alias("disposal_cost_usd"), pl.lit(5000.0).alias("carbon_cost_usd"),
    )
    hazard = pl.DataFrame({
        "asset_id": ["A"], "wind_grid_id": [1], "climate_zone": ["3A"], "terrain_id": [3],
        **{column: [75.0] for column in GUST_COLUMNS},
    })
    climate = pl.DataFrame({
        "wind_grid_id": [1] * 3, "year": list(range(2026, 2029)),
        "climate_scale_factor": [1.0] * 3, "climate_scale_rule": ["fixture"] * 3,
    })
    curves = pl.DataFrame([
        {"climate_zone": "3A", "lookup_roof_age": age, "source_material_id": material,
         "terrain_id": 3, "wind_speed_mph": wind, "building_loss_ratio": loss,
         "source_curve_count": 1, "fragility_proxy_id": proxy,
         "fragility_mapping_version": FRAGILITY_MAPPING_VERSION,
         "curve_aggregation_method": CURVE_AGGREGATION_METHOD}
        for age in range(1, 31) for material, proxy in MATERIAL_PROXY_IDS.items()
        for wind, loss in ((0.0, 0.0), (150.0, age / 30))
    ])
    return ProgramInputs(config, {"asset_id": "A", "parent_run_id": "fixture"}, assets, lives,
                         costs, removals, hazard, climate, curves, states)


@pytest.mark.parametrize("year", [2026, 2027, 2028])
def test_delayed_lifecycle_matches_baseline_then_installs_once(inputs, year):
    rows = inputs.states.filter(pl.col("candidate_year") == year)
    base = rows.filter(pl.col("scenario_id") == "BASELINE_CURRENT")
    for scenario in TARGETS:
        path = rows.filter(pl.col("scenario_id") == scenario)
        fields = ["year", "roof_age_years", "installation_event", "scenario_material_id", "applied_eul_years"]
        assert_frame_equal(path.filter(pl.col("year") < year).select(fields),
                           base.filter(pl.col("year") < year).select(fields))
        installed = path.filter(pl.col("year") == year).row(0, named=True)
        assert installed["roof_age_years"] == 0
        assert installed["initial_installation_event"]
        assert installed["install_sequence"] == (2 if year == 2028 else 1)
        assert installed["removed_material_id"] == "OFFICIAL_ASPHALT"
        assert installed["scenario_material_id"] == scenario.replace("NEW_", "OFFICIAL_")


def test_explicit_start_is_identical_and_invalid_year_rejected(inputs):
    a = build_annual_scenario_state(inputs.assets, inputs.service_lives, inputs.config)
    b = build_annual_scenario_state(inputs.assets, inputs.service_lives, inputs.config, installation_year=2026)
    assert_frame_equal(a, b)
    for year in (2025, 2029, 2026.5, True):
        with pytest.raises(ValueError, match="installation_year"):
            build_annual_scenario_state(inputs.assets, inputs.service_lives, inputs.config, installation_year=year)


def test_evaluation_shape_same_material_and_carbon_exclusion(inputs):
    candidates, annual = evaluate(inputs)
    assert candidates.height == 3 * 3 * 2
    assert annual.height == 3 * 3 * 4
    same = candidates.filter(
        (pl.col("target_scenario") == "NEW_ASPHALT") & (pl.col("counterfactual") == "CONVENTIONAL_AT_YEAR")
    )
    assert same["economic_grant_usd"].to_list() == [0, 0, 0]
    assert same["npv_at_installation_usd"].to_list() == [0, 0, 0]
    assert same.filter(pl.col("recommended"))["candidate_year"].item() == 2026
    carbon = replace(inputs, config=inputs.config.model_copy(
        update={"enabled_cost_streams": [CostStream.MATERIAL, CostStream.LABOR, CostStream.CARBON]},
    ))
    assert_frame_equal(candidates, evaluate(carbon)[0])


def _fixture_annual(inputs):
    _, annual = evaluate(inputs)
    return annual.with_columns(
        pl.when((pl.col("year") == pl.col("candidate_year")) & (pl.col("scenario_id") == "NEW_METAL"))
        .then(20000.0)
        .when((pl.col("year") == pl.col("candidate_year")) & (pl.col("scenario_id") == "NEW_ASPHALT"))
        .then(12000.0).otherwise(0.0).alias("installation_event_capex_usd"),
        pl.lit(0.0).alias("enabled_event_disposal_cost_usd"),
        pl.when((pl.col("year") == 2028) & (pl.col("scenario_id") == "NEW_ASPHALT"))
        .then(3000.0).otherwise(0.0).alias("annual_repair_cost_usd"),
        pl.lit(0.0).alias("enabled_loss_of_use_usd"),
    )


def test_exact_grant_upfront_fixture_and_payment_timing(inputs):
    annual = _fixture_annual(inputs)
    config = inputs.config.model_copy(update={"real_discount_rate": 0.0})
    results = summarize(annual, config)
    row = results.filter(
        (pl.col("target_scenario") == "NEW_METAL") & (pl.col("counterfactual") == "CONVENTIONAL_AT_YEAR")
        & (pl.col("candidate_year") == 2026)
    ).row(0, named=True)
    assert row["upfront_gap_usd"] == 8000
    assert row["economic_grant_usd"] == 5000
    assert row["grant_adjusted_npv_usd"] == 0
    annual = annual.with_columns(
        pl.when((pl.col("scenario_id") == "NEW_METAL") & (pl.col("year") == pl.col("candidate_year")))
        .then(1210.0).otherwise(0.0).alias("installation_event_capex_usd"),
        pl.lit(0.0).alias("annual_repair_cost_usd"),
    )
    row = summarize(annual, config.model_copy(update={"real_discount_rate": 0.1})).filter(
        (pl.col("target_scenario") == "NEW_METAL") & (pl.col("counterfactual") == "KEEP_TO_EOL")
        & (pl.col("candidate_year") == 2028)
    ).row(0, named=True)
    assert row["economic_grant_usd"] == 1210
    assert row["npv_at_start_usd"] == pytest.approx(-1000)


def test_missing_costs_remain_unavailable_and_recommendation_is_provisional(inputs):
    annual = _fixture_annual(inputs).with_columns(
        pl.when((pl.col("scenario_id") == "NEW_METAL") & (pl.col("candidate_year") == 2026))
        .then(None).otherwise(pl.col("annual_repair_cost_usd")).alias("annual_repair_cost_usd"),
    )
    results = summarize(annual, inputs.config).filter(pl.col("target_scenario") == "NEW_METAL")
    assert results["recommendation_provisional"].all()
    assert results.filter(pl.col("candidate_year") == 2026)["economic_grant_usd"].null_count() == 2
    assert results.filter(pl.col("candidate_year") == 2026)["upfront_gap_usd"].null_count() == 0
    assert not results.filter(pl.col("candidate_year") == 2026)["recommended"].any()
    with pytest.raises(ValueError, match="duplicate"):
        summarize(pl.concat([annual, annual.head(1)]), inputs.config)
    with pytest.raises(ValueError, match="cover every"):
        summarize(annual.slice(1), inputs.config)


def test_persist_reload_reproduce_and_reject_corruption(inputs, tmp_path):
    run = publish_program(inputs, tmp_path)
    root = Path(run["run_root"])
    repeated = publish_program(inputs, tmp_path)
    assert repeated["cache_hit"]
    reordered = replace(inputs, climate=inputs.climate.reverse(), curves=inputs.curves.reverse())
    assert publish_program(reordered, tmp_path)["run_id"] == run["run_id"]
    metadata, candidates, annual = load_program(root)
    restored = load_snapshot(root)
    assert_frame_equal(evaluate(restored)[0], candidates)
    assert_frame_equal(evaluate(restored)[1], annual)
    assert metadata["candidate_count"] == 18
    changed = replace(inputs, config=inputs.config.model_copy(update={"real_discount_rate": 0.1}))
    assert publish_program(changed, tmp_path)["run_id"] != run["run_id"]
    (root / "candidates.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="corrupt"):
        load_program(root)


def test_one_year_horizon_positive_npv_and_no_valid_recommendation(inputs):
    config = inputs.config.model_copy(update={"start_year": 2028})
    annual = _fixture_annual(inputs).filter(
        (pl.col("candidate_year") == 2028) & (pl.col("year") == 2028)
    ).with_columns(
        pl.lit(0.0).alias("installation_event_capex_usd"),
    )
    row = summarize(annual, config).filter(
        (pl.col("target_scenario") == "NEW_METAL") & (pl.col("counterfactual") == "CONVENTIONAL_AT_YEAR")
    ).row(0, named=True)
    assert row["npv_at_installation_usd"] == 3000
    assert row["economic_grant_usd"] == 0
    assert row["grant_adjusted_npv_usd"] == 3000
    missing = annual.with_columns(pl.lit(None, dtype=pl.Float64).alias("annual_repair_cost_usd"))
    results = summarize(missing, config)
    assert results["economic_grant_usd"].null_count() == 6
    assert not results["recommended"].any()


def test_cent_level_tie_chooses_earliest_year(inputs):
    annual = _fixture_annual(inputs).with_columns(
        pl.when((pl.col("scenario_id") == "NEW_METAL") & (pl.col("year") == pl.col("candidate_year")))
        .then(pl.when(pl.col("candidate_year") == 2026).then(10.004).otherwise(10.001))
        .otherwise(0.0).alias("installation_event_capex_usd"),
        pl.lit(0.0).alias("annual_repair_cost_usd"),
    )
    rows = summarize(annual, inputs.config).filter(
        (pl.col("target_scenario") == "NEW_METAL") & (pl.col("counterfactual") == "KEEP_TO_EOL")
    )
    assert rows.filter(pl.col("recommended"))["candidate_year"].item() == 2026


def test_overdue_roof_and_multiple_future_replacements(inputs):
    config = inputs.config.model_copy(update={"end_year": 2034})
    lives = inputs.service_lives.with_columns(pl.lit(2).alias("applied_physical_eul_years"))
    assets = inputs.assets.with_columns(pl.lit(4).alias("input_roof_age"))
    state = build_annual_scenario_state(assets, lives, config, installation_year=2029)
    path = state.filter(pl.col("scenario_id") == "NEW_METAL")
    assert path.filter(pl.col("installation_event"))["year"].to_list() == [2026, 2028, 2029, 2031, 2033]
    assert path.filter(pl.col("year") == 2029)["install_sequence"].item() == 3
    assert path.filter(pl.col("year") == 2031)["removed_material_id"].item() == "OFFICIAL_METAL"


def test_tile_proxy_begins_at_installation_not_before(inputs):
    from cadence.program.contracts import damage_state

    state = inputs.states.filter(pl.col("candidate_year") == 2028)
    effective = damage_state(state, True).filter(pl.col("scenario_id") == "NEW_TILE")
    assert effective["scenario_material_id"].to_list() == [
        "OFFICIAL_ASPHALT", "OFFICIAL_ASPHALT", "OFFICIAL_METAL",
    ]
