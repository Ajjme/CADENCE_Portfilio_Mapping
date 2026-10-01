from pathlib import Path

import polars as pl

from cadence.reference_data.fragility import load_terrain_averaged_curve


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