from pathlib import Path

import polars as pl
import pytest

from cadence.economics.contracts import EconomicsRunConfig
from cadence.economics.labor import build_annual_labor_costs

MAPPING_ROOT = Path("Data_Catalogs/Mapping")


def _config() -> EconomicsRunConfig:
    return EconomicsRunConfig.model_validate(
        {
            "installed_cost_overrides": {
                material: {
                    "installed_usd_per_sqft": 10.0,
                    "material_share": 0.5,
                    "labor_share": 0.5,
                }
                for material in (
                    "OFFICIAL_ASPHALT",
                    "OFFICIAL_METAL",
                    "OFFICIAL_TILE",
                )
            },
            "default_roof_shape": "flat",
            "default_roof_deck_attachment": "6d_6in_12in",
            "default_roof_wall_connection": "strap",
        }
    )


def _build(assets: pl.DataFrame) -> pl.DataFrame:
    return build_annual_labor_costs(
        assets,
        _config(),
        Path("Data/Labor/Productivity/roof_labor_productivity_parameters.csv"),
        Path("Data/Labor/Escalation/labor_wage_projections_2026_2050.parquet"),
        Path("Data/Labor/Start_Year_2026/labor_wages_long.parquet"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )


def test_builds_annual_labor_for_each_official_class() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "roof_area_sqft": [1_000.0],
            "labor_market_id": ["0010180"],
            "roof_shape": [None],
            "roof_deck_attachment": [None],
            "roof_wall_connection": [None],
        }
    )

    result = _build(assets)

    assert result.height == 75
    assert result["source_labor_usd_per_sqft"].min() > 0
    assert result.filter(pl.col("year") == 2026)["labor_growth_factor"].to_list() == pytest.approx(
        [1.0, 1.0, 1.0]
    )
    assert result["roof_shape_default_applied"].all()
    assert result["labor_productivity_provisional"].all()


def test_rejects_unknown_labor_market_id() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "roof_area_sqft": [1_000.0],
            "labor_market_id": ["missing"],
            "roof_shape": ["flat"],
            "roof_deck_attachment": ["6d_6in_12in"],
            "roof_wall_connection": ["strap"],
        }
    )

    with pytest.raises(ValueError, match="missing for labor_market_id"):
        _build(assets)