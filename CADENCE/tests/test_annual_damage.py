from pathlib import Path

import polars as pl
import pytest

from cadence.vulnerability.annual_damage import (
    GUST_COLUMNS,
    build_annual_scenario_damage,
)


def _hazard() -> pl.DataFrame:
    rows = {
        "asset_id": ["A-1"] * 3,
        "wind_grid_id": [1] * 3,
        "climate_zone": ["3A"] * 3,
        "terrain_id": [3] * 3,
        "official_material_id": [
            "OFFICIAL_ASPHALT",
            "OFFICIAL_METAL",
            "OFFICIAL_TILE",
        ],
    }
    rows.update({column: [75.0] * 3 for column in GUST_COLUMNS})
    return pl.DataFrame(rows)


def _factors(*years: int, factor: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "wind_grid_id": [1] * len(years),
            "year": list(years),
            "climate_scale_factor": [factor] * len(years),
            "climate_scale_rule": ["source_year"] * len(years),
        }
    )


def test_recalculates_damage_by_age_and_deduplicates_shared_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1", "A-1", "A-1"],
            "year": [2026, 2026, 2027],
            "scenario_id": ["BASELINE_CURRENT", "NEW_ASPHALT", "NEW_ASPHALT"],
            "scenario_material_id": ["OFFICIAL_ASPHALT"] * 3,
            "lookup_roof_age": [1, 1, 2],
            "age_capped": [False, False, False],
        }
    )
    calls = []

    def fake_curve(
        fragility_root: Path,
        climate_zone: str,
        roof_age: int,
        official_material_id: str,
        terrain_id: int,
    ) -> pl.DataFrame:
        calls.append((climate_zone, roof_age, official_material_id, terrain_id))
        return pl.DataFrame(
            {
                "wind_speed_mph": [50.0, 100.0],
                "building_loss_ratio": [0.0, roof_age / 10.0],
            }
        )

    monkeypatch.setattr(
        "cadence.vulnerability.annual_damage.load_terrain_averaged_curve", fake_curve
    )

    result = build_annual_scenario_damage(
        state, _hazard(), Path("unused"), _factors(2026, 2027)
    )

    assert len(calls) == 2
    age_1 = result.filter(pl.col("lookup_roof_age") == 1)
    age_2 = result.filter(pl.col("lookup_roof_age") == 2)
    assert age_1["expected_damage_ratio"].n_unique() == 1
    assert age_2["expected_damage_ratio"].item() > age_1["expected_damage_ratio"].item(0)
    assert result["damage_incomplete"].to_list() == [False, False, False]


def test_preserves_chronological_age_cap_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "year": [2026],
            "scenario_id": ["BASELINE_CURRENT"],
            "scenario_material_id": ["OFFICIAL_METAL"],
            "lookup_roof_age": [30],
            "age_capped": [True],
        }
    )
    monkeypatch.setattr(
        "cadence.vulnerability.annual_damage.load_terrain_averaged_curve",
        lambda *_: pl.DataFrame(
            {
                "wind_speed_mph": [50.0, 100.0],
                "building_loss_ratio": [0.0, 0.5],
            }
        ),
    )

    result = build_annual_scenario_damage(
        state, _hazard(), Path("unused"), _factors(2026)
    )

    assert result.row(0, named=True)["age_capped"] is True
    assert result.row(0, named=True)["lookup_roof_age"] == 30


def test_rejects_inconsistent_asset_hazard_fields() -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "year": [2026],
            "scenario_id": ["BASELINE_CURRENT"],
            "scenario_material_id": ["OFFICIAL_ASPHALT"],
            "lookup_roof_age": [1],
            "age_capped": [False],
        }
    )
    hazard = _hazard().with_columns(
        pl.when(pl.col("official_material_id") == "OFFICIAL_METAL")
        .then(pl.lit(80.0))
        .otherwise(pl.col(GUST_COLUMNS[0]))
        .alias(GUST_COLUMNS[0])
    )

    with pytest.raises(ValueError, match="inconsistent hazard"):
        build_annual_scenario_damage(state, hazard, Path("unused"), _factors(2026))


def test_scales_gusts_before_fragility_interpolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1", "A-1", "A-1"],
            "year": [2026, 2027, 2028],
            "scenario_id": ["LOW", "UNCHANGED", "HIGH"],
            "scenario_material_id": ["OFFICIAL_ASPHALT"] * 3,
            "lookup_roof_age": [1] * 3,
            "age_capped": [False] * 3,
        }
    )
    factors = pl.DataFrame(
        {
            "wind_grid_id": [1, 1, 1],
            "year": [2026, 2027, 2028],
            "climate_scale_factor": [0.8, 1.0, 1.2],
            "climate_scale_rule": ["source_year"] * 3,
        }
    )
    monkeypatch.setattr(
        "cadence.vulnerability.annual_damage.load_terrain_averaged_curve",
        lambda *_: pl.DataFrame(
            {
                "wind_speed_mph": [50.0, 100.0],
                "building_loss_ratio": [0.0, 1.0],
            }
        ),
    )

    result = build_annual_scenario_damage(state, _hazard(), Path("unused"), factors)

    assert result["climate_scaled_rp_10_3sec_gust"].to_list() == pytest.approx(
        [60.0, 75.0, 90.0]
    )
    assert result["rp_10_3sec_gust"].to_list() == [75.0, 75.0, 75.0]
    assert result["expected_damage_ratio"].is_sorted()


def test_rejects_missing_or_invalid_climate_factors() -> None:
    state = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "year": [2026],
            "scenario_id": ["BASELINE_CURRENT"],
            "scenario_material_id": ["OFFICIAL_ASPHALT"],
            "lookup_roof_age": [1],
            "age_capped": [False],
        }
    )

    with pytest.raises(ValueError, match="missing one or more"):
        build_annual_scenario_damage(state, _hazard(), Path("unused"), _factors(2027))
    with pytest.raises(ValueError, match="finite and positive"):
        build_annual_scenario_damage(
            state, _hazard(), Path("unused"), _factors(2026, factor=0.0)
        )