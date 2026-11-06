"""Resolve annual wind climate-scale factors for selected CONUS404 cells."""

from pathlib import Path
from typing import Dict, List, Set

import polars as pl

BASELINE_THROUGH_YEAR = 2024
SOURCE_FIRST_YEAR = 2025
SOURCE_LAST_YEAR = 2050
EXTRAPOLATION_START_YEAR = 2040
GRID_ID_MULTIPLIER = 65_536
CLIMATE_FACTOR_COLUMNS = (
    "wind_grid_id",
    "year",
    "climate_scale_factor",
    "climate_scale_rule",
)


def resolve_climate_scale_factors(
    climate_delta_path: Path,
    required_keys: pl.DataFrame,
) -> pl.DataFrame:
    """Return one validated wind-speed scale factor per requested grid cell and year."""
    _require_columns(required_keys, ("wind_grid_id", "year"), "required_keys")
    keys = required_keys.select("wind_grid_id", "year").unique().sort(
        "wind_grid_id", "year"
    )
    if keys.is_empty():
        return pl.DataFrame(
            schema={
                "wind_grid_id": pl.UInt64,
                "year": pl.Int64,
                "climate_scale_factor": pl.Float64,
                "climate_scale_rule": pl.String,
            }
        )
    if keys.filter(pl.col("wind_grid_id").is_null() | pl.col("year").is_null()).height:
        raise ValueError("required climate-factor keys cannot contain null values")
    if not keys.schema["wind_grid_id"].is_integer() or not keys.schema["year"].is_integer():
        raise ValueError("wind_grid_id and year must be integer columns")

    keys = keys.with_columns(
        pl.col("wind_grid_id").cast(pl.UInt64),
        pl.col("year").cast(pl.Int64),
    )
    source_years = sorted(
        year
        for year in keys["year"].unique().to_list()
        if SOURCE_FIRST_YEAR <= year <= SOURCE_LAST_YEAR
    )
    extrapolation_required = bool(
        keys.filter(pl.col("year") > SOURCE_LAST_YEAR).height
    )
    required_scale_years: Set[int] = set(source_years)
    if extrapolation_required:
        required_scale_years.update((EXTRAPOLATION_START_YEAR, SOURCE_LAST_YEAR))

    source = _read_selected_source(climate_delta_path, keys, required_scale_years)
    resolved: List[pl.DataFrame] = []
    for year in keys["year"].unique(maintain_order=True).to_list():
        year_keys = keys.filter(pl.col("year") == year)
        if year <= BASELINE_THROUGH_YEAR:
            factors = year_keys.with_columns(
                pl.lit(1.0).alias("climate_scale_factor"),
                pl.lit("baseline").alias("climate_scale_rule"),
            )
        elif year <= SOURCE_LAST_YEAR:
            factors = year_keys.join(
                source.select(
                    "wind_grid_id",
                    pl.col(f"scale_{year}").cast(pl.Float64).alias(
                        "climate_scale_factor"
                    ),
                ),
                on="wind_grid_id",
                how="left",
                validate="m:1",
            ).with_columns(pl.lit("source_year").alias("climate_scale_rule"))
        else:
            factors = year_keys.join(
                source.select(
                    "wind_grid_id",
                    (
                        pl.col(f"scale_{SOURCE_LAST_YEAR}")
                        + (year - SOURCE_LAST_YEAR)
                        * (
                            pl.col(f"scale_{SOURCE_LAST_YEAR}")
                            - pl.col(f"scale_{EXTRAPOLATION_START_YEAR}")
                        )
                        / (SOURCE_LAST_YEAR - EXTRAPOLATION_START_YEAR)
                    )
                    .cast(pl.Float64)
                    .alias("climate_scale_factor"),
                ),
                on="wind_grid_id",
                how="left",
                validate="m:1",
            ).with_columns(
                pl.lit("linear_2040_2050_extrapolation").alias(
                    "climate_scale_rule"
                )
            )
        resolved.append(factors)

    result = pl.concat(resolved).select(CLIMATE_FACTOR_COLUMNS).sort(
        "wind_grid_id", "year"
    )
    invalid = result.filter(
        pl.col("climate_scale_factor").is_null()
        | ~pl.col("climate_scale_factor").is_finite()
        | (pl.col("climate_scale_factor") <= 0)
    )
    if invalid.height:
        examples = invalid.select("wind_grid_id", "year").head(5).to_dicts()
        raise ValueError(
            f"climate scale factors must be finite and positive; invalid keys: {examples}"
        )
    if result.height != keys.height:
        raise ValueError("climate-factor resolution did not produce exactly one row per key")
    return result


def _read_selected_source(
    path: Path,
    keys: pl.DataFrame,
    required_scale_years: Set[int],
) -> pl.DataFrame:
    if not required_scale_years:
        return pl.DataFrame({"wind_grid_id": []}, schema={"wind_grid_id": pl.UInt64})
    schema = pl.read_parquet_schema(path)
    required_columns = {
        "lat_idx",
        "lon_idx",
        *(f"scale_{year}" for year in required_scale_years),
    }
    missing = sorted(required_columns - set(schema.names()))
    if missing:
        raise ValueError(f"climate delta is missing required columns: {missing}")
    nonnumeric = sorted(
        column for column in required_columns if not schema[column].is_numeric()
    )
    if nonnumeric:
        raise ValueError(f"climate delta columns must be numeric: {nonnumeric}")

    selected_grid_ids = keys.filter(pl.col("year") > BASELINE_THROUGH_YEAR)[
        "wind_grid_id"
    ].unique()
    source = (
        pl.scan_parquet(path)
        .select(sorted(required_columns))
        .with_columns(
            (
                pl.col("lat_idx").cast(pl.UInt64) * GRID_ID_MULTIPLIER
                + pl.col("lon_idx").cast(pl.UInt64)
            ).alias("wind_grid_id")
        )
        .filter(pl.col("wind_grid_id").is_in(selected_grid_ids.implode()))
        .collect()
    )
    duplicate_keys = source.group_by("wind_grid_id").len().filter(pl.col("len") != 1)
    if duplicate_keys.height:
        raise ValueError("climate delta contains duplicate selected grid keys")
    missing_grid_ids = selected_grid_ids.to_frame().join(
        source.select("wind_grid_id"), on="wind_grid_id", how="anti"
    )
    if missing_grid_ids.height:
        examples = missing_grid_ids.head(5).to_series().to_list()
        raise ValueError(f"climate delta is missing selected wind grid IDs: {examples}")
    return source


def _require_columns(frame: pl.DataFrame, columns: tuple, name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")