import zipfile
from pathlib import Path

import geopandas as gpd
import polars as pl
import pytest
from openpyxl import Workbook
from shapely.geometry import Polygon

from cadence.reference_data.economics_assets import (
    _assign_polygon_geography,
    asset_search_boxes,
    attach_economics_geography,
    build_selected_zcta_crosswalk,
    read_economics_asset_workbook,
)

MAPPING_ROOT = Path("Data_Catalogs/Mapping")


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(
        [
            "asset_id", "latitude", "longitude", "current_roof_type", "roof_age",
            "roof_area_sqft", "roof_shape", "roof_deck_attachment",
            "roof_wall_connection",
        ]
    )
    sheet.append(
        ["A-1", 35.99, -78.90, "metal", 15, 750, "Gable", '6d @ 6"/12"', "Strap"]
    )
    workbook.save(path)


def _write_crosswalks(root: Path) -> tuple:
    zcta = root / "zcta.csv"
    zcta.write_text(
        "blk2010gj,blk2010ge,zcta2020gj,zcta2020ge,parea,weight\n"
        "G37006300000000000,370630001001000,G27701,27701,1,0.8\n"
        "G37010100000000000,371010001001000,G27701,27701,1,0.2\n",
        encoding="utf-8",
    )
    cbsa_csv = root / "cbsa.csv"
    cbsa_csv.write_text(
        "blk2010gj,blk2010ge,cbsa2020gj,cbsa2020ge,parea,weight\n"
        "G37006300000000000,370630001001000,G20500,20500,1,1\n"
        "G37010100000000000,371010001001000,G22180,22180,1,1\n",
        encoding="utf-8",
    )
    archive = root / "cbsa.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.write(cbsa_csv, arcname="nhgis_blk2010_cbsa2020.csv")
    return zcta, archive


def test_reads_and_normalizes_economics_workbook(tmp_path: Path) -> None:
    workbook = tmp_path / "assets.xlsx"
    _write_workbook(workbook)

    assets = read_economics_asset_workbook(
        workbook,
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    row = assets.row(0, named=True)

    assert row["official_current_material_id"] == "OFFICIAL_METAL"
    assert row["input_roof_age"] == 15
    assert row["roof_shape"] == "gable"
    assert row["roof_deck_attachment"] == "6d_6in_12in"
    assert row["roof_wall_connection"] == "strap"
    assert row["default_applied"] is True


def test_selects_dominant_county_and_cbsa(tmp_path: Path) -> None:
    zcta, cbsa = _write_crosswalks(tmp_path)

    result = build_selected_zcta_crosswalk(["27701"], zcta, cbsa)
    row = result.row(0, named=True)

    assert row["county_fips"] == "37063"
    assert row["cbsa_code"] == "20500"


def test_attaches_all_economics_geographies(tmp_path: Path) -> None:
    workbook = tmp_path / "assets.xlsx"
    _write_workbook(workbook)
    assets = read_economics_asset_workbook(
        workbook,
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    polygon = Polygon([(-79.1, 35.8), (-78.7, 35.8), (-78.7, 36.1), (-79.1, 36.1)])
    zcta_geo = tmp_path / "zcta.geojson"
    gpd.GeoDataFrame(
        {"ZCTA5CE20": ["27701"]}, geometry=[polygon], crs="EPSG:4269"
    ).to_file(zcta_geo, driver="GeoJSON")
    labor_geo = tmp_path / "labor.parquet"
    gpd.GeoDataFrame(
        {"AREA": ["0020500"]}, geometry=[polygon], crs="EPSG:4267"
    ).to_parquet(labor_geo)
    wages = tmp_path / "wages.parquet"
    pl.DataFrame({"AREA": ["0020500"]}).write_parquet(wages)
    zcta, cbsa = _write_crosswalks(tmp_path)

    result = attach_economics_geography(
        assets, zcta_geo, zcta, cbsa, labor_geo, wages
    )
    row = result.row(0, named=True)

    assert row["zip_code"] == "27701"
    assert row["county_fips"] == "37063"
    assert row["cbsa_code"] == "20500"
    assert row["state_code"] == "NC"
    assert row["labor_market_id"] == "0020500"
    assert row["zip_assignment_method"] == "tiger_zcta_point_intersection"
    assert row["zip_assignment_distance_m"] == 0.0
    assert row["labor_assignment_method"] == "bls_area_point_intersection"
    assert row["labor_assignment_distance_m"] == 0.0


def test_assigns_nearest_polygon_with_distance_provenance() -> None:
    polygon = Polygon(
        [(-79.0, 35.9), (-78.9, 35.9), (-78.9, 36.0), (-79.0, 36.0)]
    )
    polygons = gpd.GeoDataFrame(
        {"zip_code": ["27701"]}, geometry=[polygon], crs="EPSG:4326"
    )
    points = gpd.GeoDataFrame(
        {"asset_id": ["A-1"]},
        geometry=gpd.points_from_xy([-78.89], [35.95]),
        crs="EPSG:4326",
    )

    result = _assign_polygon_geography(
        points,
        polygons,
        "zip_code",
        "ZCTA",
        "tiger_zcta_point_intersection",
        "tiger_zcta_nearest_within_50km",
    ).row(0, named=True)

    assert result["zip_code"] == "27701"
    assert result["zip_assignment_method"] == "tiger_zcta_nearest_within_50km"
    assert 0 < result["zip_assignment_distance_m"] < 50_000


def test_rejects_nearest_polygon_beyond_distance_limit() -> None:
    polygon = Polygon(
        [(-79.0, 35.9), (-78.9, 35.9), (-78.9, 36.0), (-79.0, 36.0)]
    )
    polygons = gpd.GeoDataFrame(
        {"zip_code": ["27701"]}, geometry=[polygon], crs="EPSG:4326"
    )
    points = gpd.GeoDataFrame(
        {"asset_id": ["A-1"]},
        geometry=gpd.points_from_xy([-77.0], [35.95]),
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="could not be resolved within 50 km"):
        _assign_polygon_geography(
            points,
            polygons,
            "zip_code",
            "ZCTA",
            "tiger_zcta_point_intersection",
            "tiger_zcta_nearest_within_50km",
        )

def test_search_boxes_reach_past_nearest_limit() -> None:
    (west, south, east, north), = asset_search_boxes([35.99], [-78.90])

    km_per_degree = 111.19
    assert (north - 35.99) * km_per_degree > 50
    assert (35.99 - south) * km_per_degree > 50
    assert (east + 78.90) * km_per_degree * 0.809 > 50  # cos(35.99 deg) ~ 0.809
    assert (-78.90 - west) * km_per_degree * 0.809 > 50


def test_search_boxes_stay_small_for_far_apart_assets() -> None:
    boxes = asset_search_boxes([35.99, 25.469, 37.556], [-78.8986, -80.49, -118.998])

    assert len(boxes) == 3
    for west, south, east, north in boxes:
        assert (east - west) < 3 and (north - south) < 3


def _attach_with_zcta_polygons(tmp_path: Path, zcta_polygons: dict, monkeypatch):
    workbook = tmp_path / "assets.xlsx"
    _write_workbook(workbook)
    assets = read_economics_asset_workbook(
        workbook,
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    zcta_geo = tmp_path / "zcta.geojson"
    gpd.GeoDataFrame(
        {"ZCTA5CE20": list(zcta_polygons)},
        geometry=list(zcta_polygons.values()),
        crs="EPSG:4269",
    ).to_file(zcta_geo, driver="GeoJSON")
    labor_polygon = Polygon([(-79.1, 35.8), (-78.7, 35.8), (-78.7, 36.1), (-79.1, 36.1)])
    labor_geo = tmp_path / "labor.parquet"
    gpd.GeoDataFrame(
        {"AREA": ["0020500"]}, geometry=[labor_polygon], crs="EPSG:4267"
    ).to_parquet(labor_geo)
    wages = tmp_path / "wages.parquet"
    pl.DataFrame({"AREA": ["0020500"]}).write_parquet(wages)
    zcta, cbsa = _write_crosswalks(tmp_path)

    rows_read = []
    real_read_file = gpd.read_file

    def spy(*args, **kwargs):
        frame = real_read_file(*args, **kwargs)
        rows_read.append(len(frame))
        return frame

    monkeypatch.setattr("cadence.reference_data.economics_assets.gpd.read_file", spy)
    result = attach_economics_geography(assets, zcta_geo, zcta, cbsa, labor_geo, wages)
    return result.row(0, named=True), rows_read


def test_reads_only_zctas_near_assets(tmp_path: Path, monkeypatch) -> None:
    near = Polygon([(-79.1, 35.8), (-78.7, 35.8), (-78.7, 36.1), (-79.1, 36.1)])
    far = Polygon([(-98.0, 38.0), (-97.9, 38.0), (-97.9, 38.1), (-98.0, 38.1)])

    row, rows_read = _attach_with_zcta_polygons(
        tmp_path, {"27701": near, "67401": far}, monkeypatch
    )

    assert row["zip_code"] == "27701"
    assert rows_read == [1]


def test_single_asset_still_finds_nearest_zcta(tmp_path: Path, monkeypatch) -> None:
    # About 18 km east of the asset, so it is outside a point-sized bounding box.
    east = Polygon([(-78.70, 35.9), (-78.60, 35.9), (-78.60, 36.1), (-78.70, 36.1)])

    row, _ = _attach_with_zcta_polygons(tmp_path, {"27701": east}, monkeypatch)

    assert row["zip_code"] == "27701"
    assert row["zip_assignment_method"] == "tiger_zcta_nearest_within_50km"
    assert 0 < row["zip_assignment_distance_m"] < 50_000
