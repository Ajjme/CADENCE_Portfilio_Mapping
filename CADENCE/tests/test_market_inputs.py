import json
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from cadence.economics import market_inputs, market_pipeline
from cadence.economics.alternative_analysis import build_annual_scenario_state
from cadence.economics.alternative_pipeline import _source_paths
from cadence.economics.contracts import CostStream
from cadence.economics.market_inputs import file_sha256, load_study_inputs, study_source_identity
from cadence.economics.market_study import MATERIALS
from cadence.vulnerability.annual_damage import GUST_COLUMNS, SCALED_GUST_COLUMNS
from test_alternative_analysis import _config, _service_lives


@pytest.fixture
def market_parent(tmp_path, monkeypatch):
    root = tmp_path / "alternatives/schema_version=v0.4.0/run_id=parent"
    root.mkdir(parents=True)
    reference = root.parents[1] / "economics_reference/schema_version=v0.3.0/run_id=reference"
    reference.mkdir(parents=True)
    (reference / "run_metadata.json").write_text(json.dumps({"run_id": "reference"}))
    config = _config().model_copy(update={
        "end_year": 2028,
        "enabled_cost_streams": frozenset({CostStream.MATERIAL, CostStream.LABOR, CostStream.DISPOSAL, CostStream.CARBON}),
    })
    assets = pl.DataFrame({
        "asset_id": ["A"], "official_current_material_id": ["OFFICIAL_ASPHALT"],
        "input_roof_age": [2], "current_roof_eul_years": [3.0],
        "roof_area_sqft": [1000.0], "state_code": ["SC"], "latitude": [34.0], "longitude": [-80.0],
    })
    asset_path = tmp_path / "economics_assets.parquet"
    assets.write_parquet(asset_path)
    states = build_annual_scenario_state(assets, _service_lives(), config)
    hazard = pl.DataFrame({
        "asset_id": ["A"], "wind_grid_id": [1], "climate_zone": ["3A"], "terrain_id": [3],
        **{column: [75.0] for column in GUST_COLUMNS},
    })
    damage_path = tmp_path / "damage.parquet"
    hazard.write_parquet(damage_path)
    damage = states.join(assets.select("asset_id", "latitude", "longitude"), on="asset_id").join(hazard, on="asset_id")
    damage = damage.with_columns(
        *(pl.col(original).alias(scaled) for original, scaled in zip(GUST_COLUMNS, SCALED_GUST_COLUMNS)),
        pl.lit(1.0).alias("climate_scale_factor"),
    )
    costs = pl.DataFrame([
        {"asset_id": "A", "year": y, "official_material_id": m,
         "roof_area_sqft": 1000.0, "installed_capex_usd": cost,
         "operational_cost_fallback_applied": False, "source_material_usd_per_sqft": cost * 0.6 / 1000,
         "disposal_cost_usd": 1.0, "carbon_cost_usd": 1.0}
        for y in range(2026, 2029) for m, cost in zip(MATERIALS, (12000.0, 20000.0, 24000.0))
    ])
    for folder, frame in ((root / "annual_scenario_state", states), (root / "annual_scenario_damage", damage),
                          (reference / "annual_roof_option_costs", costs)):
        for y in range(2026, 2029):
            partition = folder / f"year={y}"
            partition.mkdir(parents=True)
            frame.filter(pl.col("year") == y).write_parquet(partition / "part.parquet")
    paths = _source_paths(Path(__file__).parents[1])
    metadata = {
        "run_id": "parent", "schema_version": "v0.4.0", "asset_count": 1,
        "economics_reference_run_id": "reference", "run_config": config.model_dump(mode="json"),
        "source_checksums": {key: file_sha256(paths[key]) for key in market_inputs.REMOVAL_SOURCES},
    }
    (root / "run_metadata.json").write_text(json.dumps(metadata))
    def fake_curve(root, zone, age, material, terrain):
        return pl.DataFrame({"wind_speed_mph": [0.0, 150.0], "building_loss_ratio": [0.0, age / 30],
                             "source_curve_count": [1, 1]})
    monkeypatch.setattr("cadence.reference_data.fragility.load_terrain_averaged_curve", fake_curve)
    monkeypatch.setattr(market_pipeline, "ALTERNATIVE_RESULTS_ROOT", root.parents[1])
    monkeypatch.setattr(market_pipeline, "STUDY_ROOT", tmp_path / "studies")
    monkeypatch.setattr(market_pipeline, "study_fragility_identity", lambda *_: "fixture")
    state = {"run_root": str(root), "run_id": "parent", "economics_ready_asset_path": str(asset_path),
             "asset_damage_result_path": str(damage_path)}
    return root, metadata, state


def test_inputs_correct_removal_material_and_snapshot_age_dependent_extension(market_parent, tmp_path):
    root, metadata, state = market_parent
    assets, prices, removals, lives, risk = load_study_inputs(
        root, Path(state["economics_ready_asset_path"]), metadata,
        Path(state["asset_damage_result_path"]), tmp_path / "snapshots",
    )
    assert assets.height == 1
    assert lives["A"]["initial_eul"] == 3
    assert len({removals["A"][2026, m]["disposal_usd"] for m in MATERIALS}) == 3
    assert all(removals["A"][2026, m]["disposal_usd"] != 1.0 for m in MATERIALS)
    assert risk("A", 2100, "OFFICIAL_ASPHALT", 5) == risk("A", 2028, "OFFICIAL_ASPHALT", 5)
    assert risk("A", 2100, "OFFICIAL_ASPHALT", 5)[0] > risk("A", 2100, "OFFICIAL_ASPHALT", 0)[0]
    assert risk("A", 2100, "OFFICIAL_ASPHALT", 80) == risk("A", 2100, "OFFICIAL_ASPHALT", 29)
    assert {p.stem for p in (tmp_path / "snapshots").glob("*.parquet")} == {
        "assets", "hazard", "curves", "option_costs", "removal_costs", "service_lives",
    }
    assert pl.read_parquet(tmp_path / "snapshots/curves.parquet").select(
        "climate_zone", "lookup_roof_age", "source_material_id", "terrain_id"
    ).unique().height == 90
    assert study_source_identity(root, metadata)


def test_real_loader_publication_and_audit_round_trip(market_parent):
    root, _, state = market_parent
    manifest = market_pipeline.run_market_study(str(root), state, 10)
    output = Path(manifest["run_root"])
    market_pipeline.verify_artifacts(output, manifest)
    assert (output / "inputs/removal_costs.parquet").is_file()
    assert manifest["evaluation_end_year"] == 2088
    decisions = pd.read_parquet(output / "replacement_decisions.parquet")
    assert len(decisions) == 9
    assert decisions.incremental_npv_usd.notna().all()
    assert market_pipeline.run_market_study(str(root), state, 10)["cache_hit"]


def test_missing_source_and_enabled_loss_of_use_fail_explicitly(market_parent):
    root, metadata, state = market_parent
    metadata["source_checksums"]["material_mass"] = "changed"
    with pytest.raises(ValueError, match="differs from the parent"):
        study_source_identity(root, metadata)
    metadata["run_config"]["enabled_cost_streams"].append("loss_of_use")
    with pytest.raises(ValueError, match="loss-of-use"):
        load_study_inputs(root, Path(state["economics_ready_asset_path"]), metadata)


def test_missing_saved_price_is_not_extrapolated_inside_observed_years(market_parent):
    root, metadata, state = market_parent
    path = root.parents[1] / "economics_reference/schema_version=v0.3.0/run_id=reference/annual_roof_option_costs/year=2027/part.parquet"
    pl.read_parquet(path).filter(pl.col("official_material_id") != "OFFICIAL_TILE").write_parquet(path)
    with pytest.raises(ValueError, match="missing or duplicated"):
        load_study_inputs(root, Path(state["economics_ready_asset_path"]), metadata)
