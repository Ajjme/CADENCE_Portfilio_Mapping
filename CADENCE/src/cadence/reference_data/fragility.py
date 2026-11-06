"""Extract approved HAZUS proxies and average unresolved variants by terrain."""

from pathlib import Path

import duckdb
import polars as pl

FRAGILITY_MAPPING_VERSION = "v1.0.0"
FRAGILITY_SNAPSHOT_VERSION = "v1.0.0"
CURVE_AGGREGATION_METHOD = "equal_average_unresolved_variants_within_terrain"
CURVE_KEYS = ("climate_zone", "lookup_roof_age", "source_material_id", "terrain_id")
MATERIAL_PROXY_IDS = {
    "OFFICIAL_ASPHALT": "WSF1",
    "OFFICIAL_METAL": "SERBL",
    "OFFICIAL_TILE": "MSF1",
}
TERRAIN_LABELS = {
    1: "Open",
    2: "Light Suburban",
    3: "Suburban",
    4: "Light Trees",
    5: "Trees",
}
TERRAIN_IDS_BY_LABEL = {
    label.casefold(): terrain_id for terrain_id, label in TERRAIN_LABELS.items()
}


def load_fragility_curves(fragility_root: Path, keys: pl.DataFrame) -> pl.DataFrame:
    """Load each effective curve once, retaining its analysis provenance."""
    curves = []
    for key in keys.select(CURVE_KEYS).unique().sort(CURVE_KEYS).iter_rows(named=True):
        curve = load_terrain_averaged_curve(
            fragility_root, key["climate_zone"], key["lookup_roof_age"],
            key["source_material_id"], key["terrain_id"],
        )
        curves.append(curve.with_columns(
            *(pl.lit(value).alias(name) for name, value in key.items()),
            pl.lit(MATERIAL_PROXY_IDS[key["source_material_id"]]).alias("fragility_proxy_id"),
            pl.lit(FRAGILITY_MAPPING_VERSION).alias("fragility_mapping_version"),
            pl.lit(CURVE_AGGREGATION_METHOD).alias("curve_aggregation_method"),
        ))
    if not curves:
        raise ValueError("no fragility curve keys were requested")
    result = pl.concat(curves)
    validate_fragility_curves(result)
    return result.sort([*CURVE_KEYS, "wind_speed_mph"])


def validate_fragility_curves(curves: pl.DataFrame) -> None:
    """Reject incomplete or inconsistent saved analysis curves."""
    required = {
        *CURVE_KEYS, "wind_speed_mph", "building_loss_ratio", "source_curve_count",
        "fragility_proxy_id", "fragility_mapping_version", "curve_aggregation_method",
    }
    missing = sorted(required - set(curves.columns))
    if missing:
        raise ValueError(f"fragility curves are missing required columns: {missing}")
    if curves.is_empty() or curves.select(
        pl.any_horizontal(pl.col(name).is_null() for name in sorted(required)).any()
    ).item():
        raise ValueError("fragility curves are empty or contain missing values")
    if curves.filter(
        ~pl.col("source_material_id").is_in(MATERIAL_PROXY_IDS)
        | ~pl.col("terrain_id").is_in(TERRAIN_LABELS)
        | ~pl.col("lookup_roof_age").is_between(1, 30)
        | (pl.col("lookup_roof_age") != pl.col("lookup_roof_age").floor())
        | (pl.col("fragility_mapping_version") != FRAGILITY_MAPPING_VERSION)
        | (pl.col("curve_aggregation_method") != CURVE_AGGREGATION_METHOD)
    ).height:
        raise ValueError("fragility curves have unsupported keys or mapping provenance")
    if curves.filter(
        pl.col("fragility_proxy_id")
        != pl.col("source_material_id").replace_strict(MATERIAL_PROXY_IDS)
    ).height:
        raise ValueError("fragility curve proxy does not match its source material")
    if curves.filter(
        ~pl.col("wind_speed_mph").is_finite()
        | (pl.col("wind_speed_mph") < 0)
        | ~pl.col("building_loss_ratio").is_finite()
        | ~pl.col("building_loss_ratio").is_between(0, 1)
        | ~pl.col("source_curve_count").is_finite()
        | (pl.col("source_curve_count") < 1)
        | (pl.col("source_curve_count") != pl.col("source_curve_count").floor())
    ).height:
        raise ValueError("fragility curve points or source counts are invalid")
    if curves.select([*CURVE_KEYS, "wind_speed_mph"]).is_duplicated().any():
        raise ValueError("fragility curves contain duplicate wind speeds")
    if curves.group_by(CURVE_KEYS).len().filter(pl.col("len") < 2).height:
        raise ValueError("fragility curves require at least two points per key")


def load_terrain_averaged_curve(
    fragility_root: Path,
    climate_zone: str,
    roof_age: int,
    official_material_id: str,
    terrain_id: int,
) -> pl.DataFrame:
    """Load one curve averaged across unresolved variants at the requested grain."""
    if official_material_id not in MATERIAL_PROXY_IDS:
        raise ValueError(f"unsupported official material: {official_material_id}")
    if terrain_id not in TERRAIN_LABELS:
        raise ValueError("terrain_id must be an integer from 1 to 5")
    if roof_age < 1 or roof_age > 30:
        raise ValueError("roof_age must be between 1 and 30")

    partition = fragility_root / climate_zone / f"age_{roof_age:02d}"
    curves_path = _sql_path(partition / "curves_hu.parquet")
    points_path = _sql_path(partition / "curve_points_hu.parquet")
    attributes_path = _sql_path(partition / "curve_attributes_hu.parquet")
    proxy_id = MATERIAL_PROXY_IDS[official_material_id]
    query = f"""
        WITH terrain AS (
            SELECT curve_id
            FROM read_parquet('{attributes_path}')
            WHERE key = 'terrain_id' AND TRY_CAST(value AS INTEGER) = {terrain_id}
        )
        SELECT
            p.x AS wind_speed_mph,
            AVG(p.y) AS building_loss_ratio,
            COUNT(DISTINCT c.curve_id) AS source_curve_count
        FROM read_parquet('{curves_path}') c
        JOIN terrain t ON c.curve_id = t.curve_id
        JOIN read_parquet('{points_path}') p ON c.curve_id = p.curve_id
        WHERE c.damage_type = 'building_loss'
          AND c.building_type = '{proxy_id}'
        GROUP BY p.x
        ORDER BY p.x
    """
    curve = duckdb.sql(query).pl()
    if curve.is_empty():
        raise ValueError(
            f"missing curve for {climate_zone}, age {roof_age}, "
            f"{official_material_id}, terrain {terrain_id}"
        )
    if curve.filter(
        ~pl.col("wind_speed_mph").is_finite()
        | ~pl.col("building_loss_ratio").is_finite()
    ).height:
        raise ValueError("fragility curve contains non-finite values")
    if curve.filter(~pl.col("building_loss_ratio").is_between(0.0, 1.0)).height:
        raise ValueError("fragility curve contains a damage ratio outside [0, 1]")
    if curve["wind_speed_mph"].is_duplicated().any():
        raise ValueError("fragility curve contains duplicate wind speeds")
    return curve


def _sql_path(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path.resolve()).replace("'", "''")