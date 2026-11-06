import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import cadence.ui.results_map as results_map


def test_zcta_filter_selects_only_requested_zips() -> None:
    assert results_map.zcta_filter(("27701", "2138")) == "ZCTA5CE20 IN ('02138', '27701')"


@pytest.mark.parametrize("identifiers", [(), ("27701'; DROP",), ("abcde",)])
def test_zcta_filter_rejects_bad_identifiers(identifiers) -> None:
    with pytest.raises(ValueError):
        results_map.zcta_filter(identifiers)


def test_loads_only_requested_zcta_boundaries(tmp_path: Path, monkeypatch) -> None:
    squares = {
        zip_code: Polygon([(x, 35.0), (x + 0.1, 35.0), (x + 0.1, 35.1), (x, 35.1)])
        for zip_code, x in (("27701", -79.0), ("27705", -78.8), ("90210", -118.4))
    }
    shapefile = tmp_path / "tl_2020_us_zcta520.shp"
    gpd.GeoDataFrame(
        {"ZCTA5CE20": list(squares)}, geometry=list(squares.values()), crs="EPSG:4269"
    ).to_file(shapefile)
    archive = tmp_path / "tl_2020_us_zcta520.zip"
    with zipfile.ZipFile(archive, "w") as target:
        for part in tmp_path.glob("tl_2020_us_zcta520.*"):
            if part.suffix != ".zip":
                target.write(part, arcname=part.name)
    monkeypatch.setattr(results_map, "ZCTA_PATH", archive)
    results_map.load_map_boundaries.clear()

    shapes = results_map.load_map_boundaries("ZIP / ZCTA", ("27701", "90210"))

    assert sorted(shapes["region_id"]) == ["27701", "90210"]
    assert shapes.crs.to_epsg() == 4326
