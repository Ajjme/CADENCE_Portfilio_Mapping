from pathlib import Path
from typing import Optional

import polars as pl
import pytest

from cadence.economics.contracts import EconomicsRunConfig
from cadence.economics.labor import _load_class_productivity, build_annual_labor_costs

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


def _build(
    assets: pl.DataFrame,
    config: Optional[EconomicsRunConfig] = None,
    base_path: Path = Path("Data/Labor/Start_Year_2026/labor_wages_long.parquet"),
) -> pl.DataFrame:
    return build_annual_labor_costs(
        assets,
        config or _config(),
        Path("Data/Labor/Productivity/roof_labor_productivity_parameters.csv"),
        Path("Data/Labor/Escalation/labor_wage_projections_2026_2050.parquet"),
        base_path,
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


def test_demand_surge_raises_source_labor_in_2026_and_2050() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "roof_area_sqft": [1_000.0],
            "labor_market_id": ["0010180"],
            "roof_shape": ["flat"],
            "roof_deck_attachment": ["6d_6in_12in"],
            "roof_wall_connection": ["strap"],
        }
    )
    baseline = _build(assets)
    config = EconomicsRunConfig.model_validate(
        {**_config().model_dump(), "demand_surge": True}
    )

    surge = _build(assets, config)

    assert surge.height == baseline.height == 75
    for year in (2026, 2050):
        surged = surge.filter(pl.col("year") == year)
        regular = baseline.filter(pl.col("year") == year)
        assert surged["source_labor_usd_per_sqft"].sum() > regular["source_labor_usd_per_sqft"].sum()
    assert surge.filter(pl.col("year") == 2026)["labor_growth_factor"].to_list() == pytest.approx(
        [1.0, 1.0, 1.0]
    )
    assert surge["labor_growth_factor"].to_list() == pytest.approx(
        baseline["labor_growth_factor"].to_list()
    )

    productivity = _load_class_productivity(
        Path("Data/Labor/Productivity/roof_labor_productivity_parameters.csv"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    ).filter(
        (pl.col("official_material_id") == "OFFICIAL_ASPHALT")
        & (pl.col("roof_shape") == "flat")
        & (pl.col("roof_deck_attachment") == "6d_6in_12in")
        & (pl.col("roof_wall_connection") == "strap")
        & (pl.col("size_bucket") == "small")
    )
    base_wages = pl.read_parquet("Data/Labor/Start_Year_2026/labor_wages_wide.parquet").filter(
        pl.col("AREA") == "0010180"
    ).select("OCC_CODE", "H_PCT90", "H_MEDIAN")
    projections = pl.read_parquet("Data/Labor/Escalation/labor_wage_projections_2026_2050.parquet").filter(
        (pl.col("AREA") == "0010180") & pl.col("PROJECTION_YEAR").is_in([2026, 2050])
    ).select("OCC_CODE", "PROJECTION_YEAR", "H_MEDIAN_CONSTRAINED_PROJECTED_WAGE")
    expected = productivity.join(
        base_wages, left_on="occupation_code", right_on="OCC_CODE", validate="m:1"
    ).join(projections, left_on="occupation_code", right_on="OCC_CODE", validate="m:m").with_columns(
        (pl.col("H_PCT90") / pl.col("H_MEDIAN") * pl.col("H_MEDIAN_CONSTRAINED_PROJECTED_WAGE"))
        .alias("surge_wage")
    ).group_by("PROJECTION_YEAR").agg(
        (
            (pl.col("base_person_hours_per_sqft") + pl.col("startup_person_hours") / 1_000)
            * pl.col("surge_wage")
        ).sum().alias("labor"),
        (pl.col("occupation_labor_share") * pl.col("surge_wage")).sum().alias("weighted_wage"),
    )
    for row in expected.iter_rows(named=True):
        actual = surge.filter(
            (pl.col("year") == row["PROJECTION_YEAR"])
            & (pl.col("official_material_id") == "OFFICIAL_ASPHALT")
        ).row(0, named=True)
        assert actual["source_labor_usd_per_sqft"] == pytest.approx(row["labor"])
        assert actual["weighted_hourly_wage_usd"] == pytest.approx(row["weighted_wage"])


@pytest.mark.parametrize(
    ("invalid_column", "invalid_value"),
    [("H_MEDIAN", 0.0), ("H_PCT90", None)],
)
def test_demand_surge_rejects_invalid_base_wages(
    tmp_path: Path, invalid_column: str, invalid_value: Optional[float]
) -> None:
    base_path = tmp_path / "labor_wages_long.parquet"
    pl.read_parquet("Data/Labor/Start_Year_2026/labor_wages_long.parquet").filter(
        pl.col("AREA") == "0010180"
    ).write_parquet(base_path)
    pl.read_parquet("Data/Labor/Start_Year_2026/labor_wages_wide.parquet").filter(
        pl.col("AREA") == "0010180"
    ).with_columns(
        pl.when(pl.col("OCC_CODE") == "47-2061")
        .then(pl.lit(invalid_value, dtype=pl.Float64))
        .otherwise(pl.col(invalid_column))
        .alias(invalid_column)
    ).write_parquet(tmp_path / "labor_wages_wide.parquet")
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"], "roof_area_sqft": [1_000.0],
            "labor_market_id": ["0010180"], "roof_shape": ["flat"],
            "roof_deck_attachment": ["6d_6in_12in"],
            "roof_wall_connection": ["strap"],
        }
    )
    config = EconomicsRunConfig.model_validate({**_config().model_dump(), "demand_surge": True})

    with pytest.raises(ValueError, match="demand surge wages.*0010180"):
        _build(assets, config, base_path)


def test_demand_surge_uses_p90_wage_provenance(tmp_path: Path) -> None:
    base_path = tmp_path / "labor_wages_long.parquet"
    pl.read_parquet("Data/Labor/Start_Year_2026/labor_wages_long.parquet").filter(
        pl.col("AREA") == "0010180"
    ).with_columns(
        pl.when(pl.col("WAGE_METRIC") == "H_PCT90")
        .then(pl.lit("p90_test_source"))
        .otherwise(pl.col("SOURCE_LEVEL"))
        .alias("SOURCE_LEVEL")
    ).write_parquet(base_path)
    pl.read_parquet("Data/Labor/Start_Year_2026/labor_wages_wide.parquet").filter(
        pl.col("AREA") == "0010180"
    ).write_parquet(tmp_path / "labor_wages_wide.parquet")
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"], "roof_area_sqft": [1_000.0],
            "labor_market_id": ["0010180"], "roof_shape": ["flat"],
            "roof_deck_attachment": ["6d_6in_12in"],
            "roof_wall_connection": ["strap"],
        }
    )
    config = EconomicsRunConfig.model_validate({**_config().model_dump(), "demand_surge": True})

    baseline = _build(assets, base_path=base_path)
    surge = _build(assets, config, base_path)

    assert all("p90_test_source" not in levels for levels in baseline["wage_source_levels"])
    assert all("p90_test_source" in levels for levels in surge["wage_source_levels"])


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