import json
from pathlib import Path

import polars as pl
import pytest

from cadence.insurance.pipeline import publish_insurance


def _physical(tmp_path: Path):
    root = tmp_path / "physical" / "schema_version=v0.4.0" / "run_id=sample"
    partition = root / "annual_alternative_analysis" / "year=2026"
    partition.mkdir(parents=True)
    pl.DataFrame({
        "asset_id": ["A"] * 4, "year": [2026] * 4,
        "scenario_id": ["BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE"],
        "annual_repair_cost_usd": [150.0] * 4,
    }).write_parquet(partition / "part-00000.parquet")
    return root, {"run_id": "sample", "schema_version": "v0.4.0"}


def _source(premium=200):
    return pl.DataFrame({
        "asset_id": ["A"], "policy_id": ["P"], "insured_value": [300],
        "deductible_amount": [100], "deductible_type": ["standard"],
        "peril": ["wind"], "current_premium": [premium],
    })


def test_publishes_snapshot_and_new_identity_for_changed_premium(tmp_path):
    root, metadata = _physical(tmp_path)
    output = tmp_path / "insurance"
    first = publish_insurance(root, metadata, _source(), "original", output)
    cached = publish_insurance(root, metadata, _source(), "original", output)
    changed = publish_insurance(root, metadata, _source(210), "changed", output)

    assert first["annual_row_count"] == 4
    assert cached["cache_hit"] is True
    assert changed["run_id"] != first["run_id"]
    assert json.loads((Path(first["run_root"]) / "run_metadata.json").read_text())["selected_workbook_sha256"] == "original"
    assert pl.read_parquet(Path(first["run_root"]) / "policy_snapshot.parquet")["policy_id"].to_list() == ["P"]
    assert pl.read_parquet(root / "annual_alternative_analysis/year=2026/part-00000.parquet")["annual_repair_cost_usd"].to_list() == [150.0] * 4


def test_rejects_policy_asset_mismatch_before_writing(tmp_path):
    root, metadata = _physical(tmp_path)
    output = tmp_path / "insurance"
    with pytest.raises(ValueError, match="policy asset IDs"):
        publish_insurance(root, metadata, _source().with_columns(pl.lit("B").alias("asset_id")), "x", output)
    assert not output.exists()