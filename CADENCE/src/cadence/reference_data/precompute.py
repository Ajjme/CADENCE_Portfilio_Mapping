"""Precompute small reference files from the large raw CADENCE inputs.

Each run of the app only needs a sliver of four large inputs. This builds
compact versions once, so the app (and later the backend) can read those
instead of the raw files:

    wind_return_periods.parquet     <- Wind_Return_Periods/gev_return_periods.csv
    zcta_county_cbsa.parquet        <- NHGIS block-to-ZCTA and block-to-CBSA crosswalks
    zcta_boundaries_lookup.parquet  <- TIGER 2020 ZCTA shapefile, lightly simplified
    zcta_boundaries_map.parquet     <- TIGER 2020 ZCTA shapefile, simplified for the map
    fragility_curves.parquet        <- Fragility_Curves/iecc2021 partitions, terrain-averaged

Every output reuses the logic the pipeline runs today, so it gives the same
answers as reading the raw files. A manifest.json next to the outputs records
the sources, settings, and row counts.

Run from the CADENCE folder after the raw files are downloaded (git lfs pull):

    python -m cadence.reference_data.precompute
    python -m cadence.reference_data.precompute --only wind fragility
"""

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import duckdb
import geopandas as gpd
import pandas as pd
import polars as pl

from cadence.reference_data.economics_assets import (
    _source_paths as economics_source_paths,
    build_full_zcta_crosswalk,
)
from cadence.reference_data.fragility import (
    CURVE_AGGREGATION_METHOD,
    CURVE_KEYS,
    FRAGILITY_MAPPING_VERSION,
    MATERIAL_PROXY_IDS,
    TERRAIN_LABELS,
)
from cadence.reference_data.year1_damage import GUST_COLUMNS, VALID_CLIMATE_ZONES
from cadence.ui.paths import CADENCE_ROOT

PRECOMPUTE_VERSION = "v1"
STEPS = ("wind", "zip_lookup", "zip_boundaries", "fragility")
OUTPUT_FILES = {
    "wind": "wind_return_periods.parquet",
    "zip_lookup": "zcta_county_cbsa.parquet",
    "zip_boundaries_lookup": "zcta_boundaries_lookup.parquet",
    "zip_boundaries_map": "zcta_boundaries_map.parquet",
    "fragility": "fragility_curves.parquet",
}
DEFAULT_OUTPUT_ROOT = CADENCE_ROOT / "Data" / "Precomputed"
WIND_SOURCE_COLUMNS = ("lat_idx", "lon_idx", "latitude", "longitude", *GUST_COLUMNS, "converged")
# results_map.load_map_boundaries simplifies ZCTAs by this much before drawing them.
MAP_SIMPLIFY_DEGREES = 0.002
# About 11 m. Only changes the ZIP for a point within ~11 m of a ZIP border.
DEFAULT_LOOKUP_SIMPLIFY_DEGREES = 0.0001
ZCTA_ID_COLUMN = "ZCTA5CE20"
ZCTA_READ_CHUNK = 5_000
ROOF_AGES = tuple(range(1, 31))
FRAGILITY_FILES = ("curves_hu.parquet", "curve_points_hu.parquet", "curve_attributes_hu.parquet")
LFS_POINTER_PREFIX = b"version https://git-lfs"


def source_paths(cadence_root: Path = CADENCE_ROOT) -> Dict[str, Path]:
    """Raw inputs, at the same paths the pipeline reads them from."""
    geography = economics_source_paths(cadence_root)
    data = cadence_root / "Data"
    return {
        "wind": data / "Wind_Return_Periods" / "gev_return_periods.csv",
        "zcta": geography["zcta"],
        "zcta_crosswalk": geography["zcta_crosswalk"],
        "cbsa_crosswalk": geography["cbsa_crosswalk"],
        "fragility": data / "Fragility_Curves" / "iecc2021",
    }


def build_wind(source: Path, output: Path) -> Dict[str, object]:
    """Keep the grid, coordinates, gust columns, and convergence flag as Parquet.

    Gusts stay in m/s like the CSV (the pipeline converts to mph after reading)
    and are stored as float32. Coordinates stay float64 so every asset still
    snaps to the same nearest grid cell.
    """
    _require_downloaded(source)
    wind = pl.read_csv(source, columns=list(WIND_SOURCE_COLUMNS))
    finite_columns = ["latitude", "longitude", *GUST_COLUMNS]
    if wind.filter(pl.any_horizontal(~pl.col(name).is_finite() for name in finite_columns)).height:
        raise ValueError("wind grid contains non-finite coordinates or gust return levels")
    if wind.select("lat_idx", "lon_idx").is_duplicated().any():
        raise ValueError("wind grid has more than one row for a grid cell")
    compact = wind.select(
        pl.col("lat_idx").cast(pl.Int32),
        pl.col("lon_idx").cast(pl.Int32),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        *(pl.col(name).cast(pl.Float32) for name in GUST_COLUMNS),
        pl.col("converged"),
    ).sort("lat_idx", "lon_idx")
    original = wind.sort("lat_idx", "lon_idx")
    rounding = max(
        float((compact[name].cast(pl.Float64) - original[name].cast(pl.Float64)).abs().max())
        for name in GUST_COLUMNS
    )
    _write_polars(compact, output, row_group_size=100_000)
    return {
        "rows": compact.height,
        "columns": compact.columns,
        "gust_units": "m/s, same as the source CSV",
        "max_gust_rounding_mps": rounding,
    }


def build_zip_lookup(zcta_crosswalk: Path, cbsa_crosswalk_zip: Path, output: Path) -> Dict[str, object]:
    """One row per ZCTA with its dominant county and CBSA."""
    _require_downloaded(zcta_crosswalk)
    _require_downloaded(cbsa_crosswalk_zip)
    lookup = build_full_zcta_crosswalk(zcta_crosswalk, cbsa_crosswalk_zip)
    if lookup.is_empty():
        raise ValueError("the NHGIS crosswalk produced no ZCTAs")
    if lookup["zip_code"].is_duplicated().any():
        raise ValueError("the ZCTA lookup has more than one row for a ZIP code")
    _write_polars(lookup.sort("zip_code"), output, row_group_size=50_000)
    return {
        "rows": lookup.height,
        "columns": lookup.columns,
        "zips_without_cbsa": int(lookup["cbsa_code"].null_count()),
    }


def build_zip_boundaries(
    zcta_zip: Path,
    lookup_output: Path,
    map_output: Path,
    lookup_tolerance: float = DEFAULT_LOOKUP_SIMPLIFY_DEGREES,
) -> Dict[str, object]:
    """Write ZCTA polygons in WGS84 twice: lightly simplified for lookups, more for the map.

    Both are GeoParquet with a bounding-box column and rows sorted so nearby
    ZIPs sit together, which lets readers fetch only the ZIPs near an asset.
    """
    if lookup_tolerance < 0:
        raise ValueError("lookup tolerance cannot be negative")
    _require_downloaded(zcta_zip)
    source = f"zip://{zcta_zip.resolve()}"
    lookup_parts: List[gpd.GeoDataFrame] = []
    map_parts: List[gpd.GeoDataFrame] = []
    start = 0
    while True:
        chunk = gpd.read_file(source, rows=slice(start, start + ZCTA_READ_CHUNK))
        if chunk.empty:
            break
        chunk = chunk[[ZCTA_ID_COLUMN, "geometry"]].to_crs("EPSG:4326")
        lookup_parts.append(_simplify(chunk, lookup_tolerance))
        map_parts.append(_simplify(chunk, MAP_SIMPLIFY_DEGREES))
        start += len(chunk)
        if len(chunk) < ZCTA_READ_CHUNK:
            break
    if not lookup_parts:
        raise ValueError("the ZCTA shapefile has no features")
    lookup = _combine(lookup_parts)
    boundaries_map = _combine(map_parts)
    _write_geoparquet(lookup, lookup_output)
    _write_geoparquet(boundaries_map, map_output)
    return {
        "rows": len(lookup),
        "crs": "EPSG:4326",
        "id_column": ZCTA_ID_COLUMN,
        "lookup_simplify_degrees": lookup_tolerance,
        "map_simplify_degrees": MAP_SIMPLIFY_DEGREES,
        "lookup_file": lookup_output.name,
        "map_file": map_output.name,
        "lookup_bytes": lookup_output.stat().st_size,
        "map_bytes": map_output.stat().st_size,
    }


def build_fragility(fragility_root: Path, output: Path) -> Dict[str, object]:
    """Every terrain-averaged curve (zone x age x material x terrain) in one file.

    Matches fragility.load_terrain_averaged_curve, run for every key at once
    per partition instead of one key at a time.
    """
    frames: List[pl.DataFrame] = []
    missing_partitions: List[str] = []
    for climate_zone in VALID_CLIMATE_ZONES:
        for roof_age in ROOF_AGES:
            partition = fragility_root / climate_zone / f"age_{roof_age:02d}"
            paths = [partition / name for name in FRAGILITY_FILES]
            if not all(path.is_file() for path in paths):
                missing_partitions.append(f"{climate_zone}/age_{roof_age:02d}")
                continue
            for path in paths:
                _require_downloaded(path)
            frames.append(_partition_curves(partition, climate_zone, roof_age))
    if not frames:
        raise FileNotFoundError(f"no fragility partitions found under {fragility_root}")
    curves = pl.concat(frames).sort([*CURVE_KEYS, "wind_speed_mph"])
    _validate_curves(curves)
    expected = {
        (zone, age, material, terrain)
        for zone in VALID_CLIMATE_ZONES
        for age in ROOF_AGES
        if f"{zone}/age_{age:02d}" not in missing_partitions
        for material in MATERIAL_PROXY_IDS
        for terrain in TERRAIN_LABELS
    }
    present = set(curves.select(CURVE_KEYS).unique().iter_rows())
    missing_curves = sorted(expected - present)
    _write_polars(curves, output, row_group_size=200_000)
    return {
        "rows": curves.height,
        "curves": len(present),
        "columns": curves.columns,
        "missing_partitions": missing_partitions,
        "missing_curve_count": len(missing_curves),
        "missing_curves_sample": [list(key) for key in missing_curves[:20]],
    }


def run(
    steps: Sequence[str] = STEPS,
    cadence_root: Path = CADENCE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    lookup_tolerance: float = DEFAULT_LOOKUP_SIMPLIFY_DEGREES,
) -> Dict[str, object]:
    """Build the requested outputs and update manifest.json."""
    unknown = sorted(set(steps) - set(STEPS))
    if unknown:
        raise ValueError(f"unknown steps: {unknown}")
    sources = source_paths(cadence_root)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    manifest = _read_manifest(manifest_path)
    for step in STEPS:
        if step not in steps:
            continue
        started = time.perf_counter()
        print(f"[precompute] {step}: building...", flush=True)
        if step == "wind":
            details = build_wind(sources["wind"], output_root / OUTPUT_FILES["wind"])
            used = {"wind": sources["wind"]}
        elif step == "zip_lookup":
            details = build_zip_lookup(
                sources["zcta_crosswalk"], sources["cbsa_crosswalk"],
                output_root / OUTPUT_FILES["zip_lookup"],
            )
            used = {name: sources[name] for name in ("zcta_crosswalk", "cbsa_crosswalk")}
        elif step == "zip_boundaries":
            details = build_zip_boundaries(
                sources["zcta"],
                output_root / OUTPUT_FILES["zip_boundaries_lookup"],
                output_root / OUTPUT_FILES["zip_boundaries_map"],
                lookup_tolerance,
            )
            used = {"zcta": sources["zcta"]}
        else:
            details = build_fragility(sources["fragility"], output_root / OUTPUT_FILES["fragility"])
            used = {"fragility": sources["fragility"]}
        seconds = time.perf_counter() - started
        if step != "zip_boundaries":
            details["file"] = OUTPUT_FILES[step]
            details["bytes"] = (output_root / OUTPUT_FILES[step]).stat().st_size
        details["seconds"] = round(seconds, 1)
        details["sources"] = {name: _describe_source(path, cadence_root) for name, path in used.items()}
        manifest["outputs"][step] = details
        print(f"[precompute] {step}: done in {seconds:.1f} s ({_size_summary(details)})", flush=True)
    manifest.update(
        {
            "precompute_version": PRECOMPUTE_VERSION,
            "fragility_mapping_version": FRAGILITY_MAPPING_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cadence_commit": _git_commit(cadence_root),
        }
    )
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def _partition_curves(partition: Path, climate_zone: str, roof_age: int) -> pl.DataFrame:
    curves_path, points_path, attributes_path = (_sql_path(partition / name) for name in FRAGILITY_FILES)
    proxies = ", ".join(f"'{proxy}'" for proxy in MATERIAL_PROXY_IDS.values())
    terrains = ", ".join(str(terrain) for terrain in TERRAIN_LABELS)
    # Same joins, filters, and averages as load_terrain_averaged_curve, grouped
    # by proxy and terrain too so one query covers every curve in the partition.
    query = f"""
        WITH terrain AS (
            SELECT curve_id, TRY_CAST(value AS INTEGER) AS terrain_id
            FROM read_parquet('{attributes_path}')
            WHERE key = 'terrain_id' AND TRY_CAST(value AS INTEGER) IN ({terrains})
        )
        SELECT
            c.building_type AS fragility_proxy_id,
            t.terrain_id,
            p.x AS wind_speed_mph,
            AVG(p.y) AS building_loss_ratio,
            COUNT(DISTINCT c.curve_id) AS source_curve_count
        FROM read_parquet('{curves_path}') c
        JOIN terrain t ON c.curve_id = t.curve_id
        JOIN read_parquet('{points_path}') p ON c.curve_id = p.curve_id
        WHERE c.damage_type = 'building_loss'
          AND c.building_type IN ({proxies})
        GROUP BY c.building_type, t.terrain_id, p.x
    """
    material_by_proxy = {proxy: material for material, proxy in MATERIAL_PROXY_IDS.items()}
    curves = duckdb.sql(query).pl()
    return curves.select(
        pl.lit(climate_zone).alias("climate_zone"),
        pl.lit(roof_age, dtype=pl.Int64).alias("lookup_roof_age"),
        pl.col("fragility_proxy_id").replace_strict(material_by_proxy).alias("source_material_id"),
        pl.col("terrain_id").cast(pl.Int64),
        pl.col("wind_speed_mph").cast(pl.Float64),
        pl.col("building_loss_ratio").cast(pl.Float64),
        pl.col("source_curve_count").cast(pl.Int64),
        pl.col("fragility_proxy_id"),
        pl.lit(FRAGILITY_MAPPING_VERSION).alias("fragility_mapping_version"),
        pl.lit(CURVE_AGGREGATION_METHOD).alias("curve_aggregation_method"),
    )


def _validate_curves(curves: pl.DataFrame) -> None:
    # The same checks load_terrain_averaged_curve runs on each curve it returns.
    if curves.filter(
        ~pl.col("wind_speed_mph").is_finite() | ~pl.col("building_loss_ratio").is_finite()
    ).height:
        raise ValueError("fragility curves contain non-finite values")
    if curves.filter(~pl.col("building_loss_ratio").is_between(0.0, 1.0)).height:
        raise ValueError("fragility curves contain a damage ratio outside [0, 1]")
    if curves.select([*CURVE_KEYS, "wind_speed_mph"]).is_duplicated().any():
        raise ValueError("fragility curves contain duplicate wind speeds")


def _simplify(frame: gpd.GeoDataFrame, tolerance: float) -> gpd.GeoDataFrame:
    if tolerance == 0:
        return frame.copy()
    result = frame.copy()
    result["geometry"] = frame.geometry.simplify(tolerance, preserve_topology=True)
    return result


def _combine(parts: List[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    frame = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    frame[ZCTA_ID_COLUMN] = frame[ZCTA_ID_COLUMN].astype(str).str.zfill(5)
    if frame[ZCTA_ID_COLUMN].duplicated().any():
        raise ValueError("the ZCTA shapefile has more than one polygon for a ZIP code")
    if (frame.geometry.isna() | frame.geometry.is_empty).any():
        raise ValueError("a ZCTA polygon is empty")
    order = frame.geometry.hilbert_distance().to_numpy().argsort(kind="stable")
    return frame.iloc[order].reset_index(drop=True)


def _write_polars(frame: pl.DataFrame, output: Path, row_group_size: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    frame.write_parquet(temporary, compression="zstd", statistics=True, row_group_size=row_group_size)
    temporary.replace(output)


def _write_geoparquet(frame: gpd.GeoDataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    frame.to_parquet(
        temporary,
        index=False,
        compression="zstd",
        write_covering_bbox=True,
        row_group_size=2_000,
    )
    temporary.replace(output)


def _require_downloaded(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing - run `git lfs pull` from the repository root")
    with path.open("rb") as source:
        if source.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX:
            raise FileNotFoundError(
                f"{path} is a Git LFS pointer, not the data - run `git lfs pull` from the repository root"
            )


def _describe_source(path: Path, cadence_root: Path) -> Dict[str, object]:
    if path.is_dir():
        files = sorted(path.rglob("*.parquet"))
        return {
            "path": _relative(path, cadence_root),
            "files": len(files),
            "bytes": sum(item.stat().st_size for item in files),
        }
    stat = path.stat()
    return {
        "path": _relative(path, cadence_root),
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_manifest(path: Path) -> Dict[str, object]:
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.setdefault("outputs", {})
        return manifest
    return {"outputs": {}}


def _git_commit(cadence_root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cadence_root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _size_summary(details: Dict[str, object]) -> str:
    if "bytes" in details:
        return f"{details['rows']:,} rows, {details['bytes'] / 1e6:.1f} MB"
    return (
        f"{details['rows']:,} ZIPs, lookup {details['lookup_bytes'] / 1e6:.1f} MB, "
        f"map {details['map_bytes'] / 1e6:.1f} MB"
    )


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _parse_args(arguments: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", choices=STEPS, default=list(STEPS), help="steps to run (default: all)")
    parser.add_argument("--cadence-root", type=Path, default=CADENCE_ROOT, help="the CADENCE folder")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT, help="where to write the outputs")
    parser.add_argument(
        "--lookup-tolerance", type=float, default=DEFAULT_LOOKUP_SIMPLIFY_DEGREES,
        help="degrees to simplify the lookup boundaries by (0 keeps full detail)",
    )
    return parser.parse_args(arguments)


def main(arguments: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(arguments)
    run(args.only, args.cadence_root, args.output, args.lookup_tolerance)


if __name__ == "__main__":
    main()
