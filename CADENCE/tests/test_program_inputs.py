import json
from pathlib import Path

import polars as pl
import pytest

from cadence.economics.alternative_pipeline import _source_paths
from cadence.program import inputs as input_module
from cadence.program.inputs import load_inputs, sha256
from test_program_analysis import inputs


@pytest.fixture
def physical(inputs, tmp_path, monkeypatch):
    root = tmp_path / "physical/schema_version=v0.4.0/run_id=fixture"
    root.mkdir(parents=True)
    reference = tmp_path / "physical/economics_reference/schema_version=v0.3.0/run_id=economics"
    reference.mkdir(parents=True)
    (reference / "run_metadata.json").write_text(json.dumps({"run_id": "economics"}))
    state = inputs.states.filter(pl.col("candidate_year") == 2026).drop("candidate_year")
    damage = state.join(inputs.hazard, on="asset_id").join(inputs.climate, on=["wind_grid_id", "year"])
    costs = inputs.option_costs.with_columns(
        pl.lit("OFFICIAL_ASPHALT").alias("official_current_material_id"),
    )
    for folder, frame in (
        (root / "annual_scenario_state", state),
        (root / "annual_scenario_damage", damage),
        (reference / "annual_roof_option_costs", costs),
    ):
        for year in range(2026, 2029):
            partition = folder / f"year={year}"
            partition.mkdir(parents=True)
            frame.filter(pl.col("year") == year).write_parquet(partition / "part.parquet")
    inputs.curves.write_parquet(root / "fragility_curves.parquet")
    repository = Path(__file__).parents[1]
    sources = _source_paths(repository)
    metadata = {
        "run_id": "fixture", "schema_version": "v0.4.0", "economics_reference_run_id": "economics",
        "run_config": inputs.config.model_dump(mode="json"),
        "source_checksums": {name: sha256(sources[name]) for name in (
            "material_mass", "mapping", "class_map", "disposal", "carbon", "scghg",
        )},
        "fragility_curves_checksum": sha256(root / "fragility_curves.parquet"),
    }
    (root / "run_metadata.json").write_text(json.dumps(metadata))
    return root, repository


def test_saved_inputs_need_no_session_or_insurance(physical):
    root, repository = physical
    result = load_inputs(root, "A", repository, Path("unused"))
    assert result.assets.height == 1
    assert result.states.height == 36
    assert result.metadata["supplemental_fragility_key_count"] == 0
    costs = result.removal_costs.filter(pl.col("year") == 2026)
    assert costs["disposal_cost_usd"].n_unique() == 3
    with pytest.raises(ValueError, match="selected home's"):
        load_inputs(root, "missing", repository, Path("unused"))


def test_source_mismatch_is_not_silently_accepted(physical):
    root, repository = physical
    path = root / "run_metadata.json"
    metadata = json.loads(path.read_text())
    metadata["source_checksums"]["material_mass"] = "changed"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="differs from the parent"):
        load_inputs(root, "A", repository, Path("unused"))


def test_missing_curves_are_supplemented_without_replacing_saved_curves(physical, inputs, monkeypatch):
    root, repository = physical
    saved = inputs.curves.filter(pl.col("lookup_roof_age") != 1)
    saved.write_parquet(root / "fragility_curves.parquet")
    path = root / "run_metadata.json"
    metadata = json.loads(path.read_text())
    metadata["fragility_curves_checksum"] = sha256(root / "fragility_curves.parquet")
    path.write_text(json.dumps(metadata))
    calls = []

    def supplement(_, keys):
        calls.append(keys)
        return inputs.curves.filter(pl.col("lookup_roof_age") == 1)

    monkeypatch.setattr(input_module, "load_fragility_curves", supplement)
    result = load_inputs(root, "A", repository, Path("supplement"))
    assert len(calls) == 1
    assert result.metadata["supplemental_fragility_key_count"] == 3
    assert result.curves.filter(pl.col("lookup_roof_age") == 1).height == 6
    (root / "fragility_curves.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="snapshot"):
        load_inputs(root, "A", repository, Path("supplement"))
