import json
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from cadence.economics import market_pipeline
from cadence.economics.market_study import COMPONENTS, MATERIALS


def test_study_publishes_annual_stock_and_uses_cache(tmp_path: Path, monkeypatch) -> None:
    results = tmp_path / "alternatives"
    root = results / "schema_version=v0.4.0" / "run_id=parent"
    root.mkdir(parents=True)
    (root / "run_metadata.json").write_text(json.dumps({
        "run_id": "parent", "asset_count": 2, "economics_reference_run_id": "reference",
        "run_config": {"start_year": 2026, "end_year": 2028, "real_discount_rate": 0.02,
                       "enabled_cost_streams": ["material", "labor"]},
    }), encoding="utf-8")
    asset_path = tmp_path / "economics_assets.parquet"
    damage_path = tmp_path / "asset_damage.parquet"
    asset_path.write_bytes(b"saved asset input")
    damage_path.write_bytes(b"saved damage input")
    monkeypatch.setattr(market_pipeline, "ALTERNATIVE_RESULTS_ROOT", results)
    monkeypatch.setattr(market_pipeline, "STUDY_ROOT", tmp_path / "studies")
    monkeypatch.setattr(market_pipeline, "study_fragility_identity", lambda _: "test-fragility")
    assets = pl.DataFrame({"asset_id": ["A", "B"], "official_current_material_id": ["OFFICIAL_ASPHALT"] * 2,
                           "input_roof_age": [2, 0]})
    prices = {asset: {(year, material): {"installed_usd": 100.0, "material_usd": 60.0, "labor_usd": 40.0}
                      for year in range(2026, 2029) for material in MATERIALS} for asset in ("A", "B")}
    removal = {asset: {(year, material): {"disposal_usd": 0.0, "carbon_usd": 0.0}
                       for year in range(2026, 2029) for material in MATERIALS} for asset in ("A", "B")}
    lives = {asset: {**dict.fromkeys(MATERIALS, 2), "initial_eul": 2 if asset == "A" else 10}
             for asset in ("A", "B")}
    monkeypatch.setattr(market_pipeline, "load_study_inputs",
                        lambda *_: (assets, prices, removal, lives, lambda *_: (1.0, 0.0)))
    state = {"run_root": str(root), "run_id": "parent", "economics_ready_asset_path": str(asset_path),
             "asset_damage_result_path": str(damage_path)}

    manifest = market_pipeline.run_market_study(str(root), state)
    assert manifest["cache_hit"] is False
    output = Path(manifest["run_root"])
    annual = pd.read_parquet(output / "annual_asset_stock.parquet")
    stock = pd.read_parquet(output / "annual_roof_share.parquet")
    totals = pd.read_parquet(output / "annual_portfolio_costs.parquet")
    assert annual.groupby("year")["asset_id"].nunique().tolist() == [2, 2, 2]
    assert stock.groupby("year")["asset_count"].sum().tolist() == [2, 2, 2]
    assert stock.groupby("year")["share_percent"].sum().tolist() == [100, 100, 100]
    for year in (2026, 2027, 2028):
        rows = annual.loc[annual["year"] == year]
        portfolio = totals.loc[totals["year"] == year].iloc[0]
        assert portfolio["total_usd"] == pytest.approx(rows[list(COMPONENTS)].sum().sum())
        assert portfolio["replacement_count"] == rows["replacement_event"].sum()
        assert portfolio["replacement_count"] == portfolio["eul_replacements"] + portfolio["damage_replacements"]
    assert market_pipeline.run_market_study(str(root), state)["cache_hit"] is True
    with pytest.raises(ValueError, match="matching active|does not match"):
        market_pipeline.run_market_study(str(root), {**state, "run_id": "other"})