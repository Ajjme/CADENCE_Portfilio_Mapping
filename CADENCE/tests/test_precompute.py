import json
import zipfile
from pathlib import Path

import geopandas as gpd
import polars as pl
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Polygon

import cadence.reference_data.precompute as precompute
import cadence.ui.results_map as results_map
from cadence.reference_data.economics_assets import (
    build_full_zcta_crosswalk,
    build_selected_zcta_crosswalk,
)
from cadence.reference_data.fragility import load_terrain_averaged_curve
from cadence.reference_data.year1_damage import GUST_COLUMNS

ZCTA_SQUARES = {
    "27701": (-79.0, 35.0),
    "27705": (-78.8, 35.0),
    "02138": (-71.1, 42.3),
    "90210": (-118.4, 34.0),
}


def _write_wind(path: Path) -> pl.DataFrame:
    rows = []
    for lat_idx in (2, 0, 1):
        for lon_idx in (1, 0):
            rows.append(
                {
                    "lat_idx": lat_idx,
                    "lon_idx": lon_idx,
                    "latitude": 35.0 + lat_idx * 0.0359123456789,
                    "longitude": -79.0 + lon_idx * 0.0441987654321,
                    **{
                        column: 30.123456789 + position + lat_idx * 0.5 + lon_idx * 0.25
                        for position, column in enumerate(GUST_COLUMNS)
                    },
                    "converged": True,
                    "extra_column": "dropped",
                }
            )
    frame = pl.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(path)
    return frame


def _write_crosswalks(zcta_path: Path, cbsa_zip_path: Path) -> None:
    zcta_path.parent.mkdir(parents=True, exist_ok=True)
    cbsa_zip_path.parent.mkdir(parents=True, exist_ok=True)
    zcta_path.write_text(
        "blk2010gj,blk2010ge,zcta2020gj,zcta2020ge,parea,weight\n"
        "G1,370630001001000,G27701,27701,1,0.8\n"
        "G2,371010001001000,G27701,27701,1,0.2\n"
        "G3,370630002001000,G27705,27705,1,1\n"
        "G4,250170001001000,G02138,2138,1,1\n"
        "G5,371830001001000,,,1,0\n",
        encoding="utf-8",
    )
    cbsa_csv = cbsa_zip_path.with_suffix(".csv")
    cbsa_csv.write_text(
        "blk2010gj,blk2010ge,cbsa2020gj,cbsa2020ge,parea,weight\n"
        "G1,370630001001000,G20500,20500,1,1\n"
        "G2,371010001001000,G22180,22180,1,1\n"
        "G3,370630002001000,G20500,20500,1,1\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(cbsa_zip_path, "w") as target:
        target.write(cbsa_csv, arcname="nhgis_blk2010_cbsa2020.csv")
    cbsa_csv.unlink()


def _wiggly_square(x: float, y: float) -> Polygon:
    # Many small steps along each edge, so simplifying actually removes points.
    steps = [index / 50 for index in range(51)]
    bottom = [(x + 0.1 * s, y + 0.0005 * (index % 2)) for index, s in enumerate(steps)]
    right = [(x + 0.1, y + 0.1 * s) for s in steps[1:]]
    top = [(x + 0.1 * (1 - s), y + 0.1) for s in steps[1:]]
    left = [(x, y + 0.1 * (1 - s)) for s in steps[1:]]
    return Polygon(bottom + right + top + left)


def _write_zcta_zip(archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    folder = archive.parent / "zcta_shapefile"
    folder.mkdir()
    shapefile = folder / "tl_2020_us_zcta520.shp"
    gpd.GeoDataFrame(
        {"ZCTA5CE20": list(ZCTA_SQUARES)},
        geometry=[_wiggly_square(x, y) for x, y in ZCTA_SQUARES.values()],
        crs="EPSG:4269",
    ).to_file(shapefile)
    with zipfile.ZipFile(archive, "w") as target:
        for part in folder.iterdir():
            target.write(part, arcname=part.name)


def _write_fragility(root: Path) -> None:
    curves = pl.DataFrame(
        {
            "curve_id": [1, 2, 3, 4, 5, 6, 7],
            "damage_type": ["building_loss"] * 4 + ["contents_loss", "building_loss", "building_loss"],
            "building_type": ["WSF1", "WSF1", "SERBL", "MSF1", "WSF1", "WSF1", "XYZ"],
        }
    )
    attributes = pl.DataFrame(
        {
            "curve_id": [1, 2, 2, 3, 4, 5, 6, 7],
            "key": ["terrain_id", "terrain_id", "geographic_case", "terrain_id", "terrain_id",
                    "terrain_id", "terrain_id", "terrain_id"],
            "value": ["1", "1", "Hawaii", "2", "1", "1", "abc", "1"],
        }
    )
    points = pl.DataFrame(
        {
            "curve_id": [1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7],
            "x": [50.0, 100.0, 150.0, 50.0, 100.0, 150.0, 60.0, 120.0, 50.0, 100.0,
                  50.0, 100.0, 50.0, 100.0, 50.0, 100.0],
            "y": [0.1, 0.4, 0.9, 0.3, 0.2, 0.7, 0.05, 0.6, 0.2, 0.8,
                  0.9, 0.9, 0.9, 0.9, 0.9, 0.9],
        }
    )
    for zone, age, shift in (("3A", 5, 0.0), ("3A", 6, 0.01)):
        partition = root / zone / f"age_{age:02d}"
        partition.mkdir(parents=True)
        curves.write_parquet(partition / "curves_hu.parquet")
        attributes.write_parquet(partition / "curve_attributes_hu.parquet")
        points.with_columns(pl.col("y") + shift).write_parquet(partition / "curve_points_hu.parquet")


def _write_all_sources(cadence_root: Path) -> dict:
    sources = precompute.source_paths(cadence_root)
    _write_wind(sources["wind"])
    _write_crosswalks(sources["zcta_crosswalk"], sources["cbsa_crosswalk"])
    _write_zcta_zip(sources["zcta"])
    _write_fragility(sources["fragility"])
    return sources


def test_wind_keeps_needed_columns_sorted_and_close(tmp_path: Path) -> None:
    source = tmp_path / "wind.csv"
    original = _write_wind(source).sort("lat_idx", "lon_idx")
    output = tmp_path / "wind.parquet"

    details = precompute.build_wind(source, output)
    wind = pl.read_parquet(output)

    assert wind.columns == list(precompute.WIND_SOURCE_COLUMNS)
    assert wind.select("lat_idx", "lon_idx").rows() == original.select("lat_idx", "lon_idx").rows()
    assert wind["latitude"].to_list() == original["latitude"].to_list()
    assert wind["longitude"].to_list() == original["longitude"].to_list()
    for column in GUST_COLUMNS:
        assert wind.schema[column] == pl.Float32
        assert wind[column].cast(pl.Float64).to_list() == pytest.approx(original[column].to_list(), rel=1e-6)
    assert details["rows"] == original.height
    assert 0 < details["max_gust_rounding_mps"] < 1e-5


def test_wind_rejects_non_finite_gusts(tmp_path: Path) -> None:
    source = tmp_path / "wind.csv"
    frame = _write_wind(source)
    frame.with_columns(pl.lit(float("nan")).alias(GUST_COLUMNS[0])).write_csv(source)

    with pytest.raises(ValueError, match="non-finite"):
        precompute.build_wind(source, tmp_path / "wind.parquet")


def test_points_at_git_lfs_when_raw_file_is_only_a_pointer(tmp_path: Path) -> None:
    source = tmp_path / "wind.csv"
    source.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="git lfs pull"):
        precompute.build_wind(source, tmp_path / "wind.parquet")


def test_full_zip_lookup_matches_one_zip_at_a_time(tmp_path: Path) -> None:
    zcta, cbsa = tmp_path / "zcta.csv", tmp_path / "cbsa.zip"
    _write_crosswalks(zcta, cbsa)
    output = tmp_path / "lookup.parquet"

    details = precompute.build_zip_lookup(zcta, cbsa, output)
    lookup = pl.read_parquet(output)

    assert lookup["zip_code"].to_list() == ["02138", "27701", "27705"]
    assert details["zips_without_cbsa"] == 1
    for zip_code in lookup["zip_code"]:
        assert lookup.filter(pl.col("zip_code") == zip_code).to_dicts() == (
            build_selected_zcta_crosswalk([zip_code], zcta, cbsa).to_dicts()
        )


def test_selected_lookup_still_rejects_unknown_zips(tmp_path: Path) -> None:
    zcta, cbsa = tmp_path / "zcta.csv", tmp_path / "cbsa.zip"
    _write_crosswalks(zcta, cbsa)

    with pytest.raises(ValueError, match="missing ZCTAs"):
        build_selected_zcta_crosswalk(["99999"], zcta, cbsa)
    assert build_full_zcta_crosswalk(zcta, cbsa).height == 3


def test_map_boundaries_match_what_the_app_draws(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "tl_2020_us_zcta520.zip"
    _write_zcta_zip(archive)
    monkeypatch.setattr(precompute, "ZCTA_READ_CHUNK", 3)
    lookup_path, map_path = tmp_path / "lookup.parquet", tmp_path / "map.parquet"

    details = precompute.build_zip_boundaries(archive, lookup_path, map_path)
    drawn = gpd.read_parquet(map_path).set_index("ZCTA5CE20")
    monkeypatch.setattr(results_map, "ZCTA_PATH", archive)
    results_map.load_map_boundaries.clear()
    app = results_map.load_map_boundaries("ZIP / ZCTA", tuple(ZCTA_SQUARES)).set_index("region_id")

    assert details["rows"] == len(ZCTA_SQUARES)
    assert sorted(drawn.index) == sorted(ZCTA_SQUARES)
    assert drawn.crs.to_epsg() == 4326
    for zip_code in ZCTA_SQUARES:
        assert drawn.geometry[zip_code].equals_exact(app.geometry[zip_code], tolerance=1e-12)


def test_lookup_boundaries_are_lightly_simplified_and_filterable(tmp_path: Path) -> None:
    archive = tmp_path / "tl_2020_us_zcta520.zip"
    _write_zcta_zip(archive)
    lookup_path, map_path = tmp_path / "lookup.parquet", tmp_path / "map.parquet"

    precompute.build_zip_boundaries(archive, lookup_path, map_path, lookup_tolerance=0)
    full = gpd.read_parquet(lookup_path).set_index("ZCTA5CE20")
    original = gpd.read_file(f"zip://{archive}").to_crs("EPSG:4326").set_index("ZCTA5CE20")
    nearby = gpd.read_parquet(lookup_path, bbox=(-79.05, 34.95, -78.85, 35.15))

    assert "bbox" in pq.read_schema(lookup_path).names
    assert sorted(nearby["ZCTA5CE20"]) == ["27701"]
    for zip_code in ZCTA_SQUARES:
        assert full.geometry[zip_code].equals_exact(original.geometry[zip_code], tolerance=1e-12)

    precompute.build_zip_boundaries(archive, lookup_path, map_path)
    light = gpd.read_parquet(lookup_path).set_index("ZCTA5CE20")
    drawn = gpd.read_parquet(map_path).set_index("ZCTA5CE20")
    for zip_code in ZCTA_SQUARES:
        assert len(light.geometry[zip_code].exterior.coords) < len(original.geometry[zip_code].exterior.coords)
        assert light.geometry[zip_code].symmetric_difference(original.geometry[zip_code]).area < 1e-5
        assert len(drawn.geometry[zip_code].exterior.coords) <= len(light.geometry[zip_code].exterior.coords)


def test_fragility_matches_one_curve_at_a_time(tmp_path: Path) -> None:
    root = tmp_path / "iecc2021"
    _write_fragility(root)
    output = tmp_path / "fragility.parquet"

    details = precompute.build_fragility(root, output)
    curves = pl.read_parquet(output)

    keys = curves.select("climate_zone", "lookup_roof_age", "source_material_id", "terrain_id").unique()
    assert sorted(keys.rows()) == [
        ("3A", age, material, terrain)
        for age in (5, 6)
        for material, terrain in (("OFFICIAL_ASPHALT", 1), ("OFFICIAL_METAL", 2), ("OFFICIAL_TILE", 1))
    ]
    for zone, age, material, terrain in keys.rows():
        expected = load_terrain_averaged_curve(root, zone, age, material, terrain)
        actual = curves.filter(
            (pl.col("climate_zone") == zone) & (pl.col("lookup_roof_age") == age)
            & (pl.col("source_material_id") == material) & (pl.col("terrain_id") == terrain)
        ).sort("wind_speed_mph")
        assert actual["wind_speed_mph"].to_list() == expected["wind_speed_mph"].to_list()
        assert actual["building_loss_ratio"].to_list() == pytest.approx(
            expected["building_loss_ratio"].to_list(), rel=1e-12
        )
        assert actual["source_curve_count"].to_list() == expected["source_curve_count"].to_list()
    assert details["curves"] == 6
    assert "3A/age_01" in details["missing_partitions"]
    assert details["missing_curve_count"] == 2 * 15 - 6


def test_fragility_rejects_out_of_range_damage(tmp_path: Path) -> None:
    root = tmp_path / "iecc2021"
    _write_fragility(root)
    points_path = root / "3A" / "age_05" / "curve_points_hu.parquet"
    pl.read_parquet(points_path).with_columns(pl.col("y") * 3).write_parquet(points_path)

    with pytest.raises(ValueError, match="outside"):
        precompute.build_fragility(root, tmp_path / "fragility.parquet")


def test_run_builds_everything_and_keeps_earlier_steps_in_the_manifest(tmp_path: Path) -> None:
    cadence_root = tmp_path / "CADENCE"
    _write_all_sources(cadence_root)
    output_root = tmp_path / "Precomputed"

    precompute.main(["--cadence-root", str(cadence_root), "--output", str(output_root)])
    precompute.run(["wind"], cadence_root, output_root)
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))

    assert set(manifest["outputs"]) == set(precompute.STEPS)
    for name in precompute.OUTPUT_FILES.values():
        assert (output_root / name).is_file()
    assert not list(output_root.glob("*.tmp"))
    assert manifest["outputs"]["wind"]["sources"]["wind"]["path"] == (
        "Data/Wind_Return_Periods/gev_return_periods.csv"
    )
    assert manifest["outputs"]["zip_lookup"]["rows"] == 3
    assert manifest["outputs"]["zip_boundaries"]["rows"] == len(ZCTA_SQUARES)
    assert manifest["outputs"]["fragility"]["curves"] == 6
