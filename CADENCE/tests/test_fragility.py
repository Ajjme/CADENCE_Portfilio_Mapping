from pathlib import Path

import polars as pl
import pytest

from cadence.reference_data.fragility import (
    load_fragility_curves,
    load_terrain_averaged_curve,
    validate_fragility_curves,
)


def test_terrain_curve_ignores_nonnumeric_attribute_values(tmp_path: Path) -> None:
    partition = tmp_path / "3A" / "age_05"
    partition.mkdir(parents=True)
    pl.DataFrame(
        {"curve_id": [1], "damage_type": ["building_loss"], "building_type": ["WSF1"]}
    ).write_parquet(partition / "curves_hu.parquet")
    pl.DataFrame(
        {
            "curve_id": [1, 1],
            "key": ["terrain_id", "geographic_case"],
            "value": ["1", "Hawaii"],
        }
    ).write_parquet(partition / "curve_attributes_hu.parquet")
    pl.DataFrame(
        {"curve_id": [1, 1], "x": [50.0, 100.0], "y": [0.1, 0.8]}
    ).write_parquet(partition / "curve_points_hu.parquet")

    curve = load_terrain_averaged_curve(tmp_path, "3A", 5, "OFFICIAL_ASPHALT", 1)

    assert curve["building_loss_ratio"].to_list() == [0.1, 0.8]


@pytest.mark.parametrize("problem", ["duplicate", "single_point", "nan", "ratio", "count", "proxy", "mapping", "null"])
def test_curve_snapshot_validation_rejects_invalid_points(monkeypatch, problem):
    monkeypatch.setattr(
        "cadence.reference_data.fragility.load_terrain_averaged_curve",
        lambda *_: pl.DataFrame({
            "wind_speed_mph": [50.0, 100.0],
            "building_loss_ratio": [0.1, 0.8], "source_curve_count": [2, 2],
        }),
    )
    curves = load_fragility_curves(Path("unused"), pl.DataFrame({
        "climate_zone": ["3A"], "lookup_roof_age": [5],
        "source_material_id": ["OFFICIAL_ASPHALT"], "terrain_id": [1],
    }))
    if problem == "duplicate":
        curves = pl.concat([curves, curves.head(1)])
    elif problem == "single_point":
        curves = curves.head(1)
    else:
        column, value = {
            "nan": ("wind_speed_mph", float("nan")),
            "ratio": ("building_loss_ratio", 1.1),
            "count": ("source_curve_count", 0),
            "proxy": ("fragility_proxy_id", "SERBL"),
            "mapping": ("fragility_mapping_version", "unknown"),
            "null": ("terrain_id", None),
        }[problem]
        curves = curves.with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError):
        validate_fragility_curves(curves)