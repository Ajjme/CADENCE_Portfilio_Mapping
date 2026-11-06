"""Material reference lookups for the CADENCE economics pipeline."""

from pathlib import Path

import polars as pl

from cadence.economics.contracts import END_YEAR, OFFICIAL_MATERIAL_CLASSES, START_YEAR

ASSET_GEOGRAPHY_COLUMNS = ("asset_id", "zip_code", "cbsa_code", "state_code")


def build_material_price_lookup(
    assets: pl.DataFrame,
    price_root: Path,
    mapping_path: Path,
    class_map_path: Path,
) -> pl.DataFrame:
    """Resolve exact subtype prices by geography, then consolidate official classes."""
    _require_columns(assets, ASSET_GEOGRAPHY_COLUMNS, "assets")
    asset_geography = assets.select(ASSET_GEOGRAPHY_COLUMNS).with_columns(
        pl.col("zip_code").cast(pl.String).str.zfill(5),
        pl.col("cbsa_code").cast(pl.String).str.zfill(5),
        pl.col("state_code").cast(pl.String).str.to_uppercase(),
    )
    source_map = _domain_source_map(mapping_path, "material_price", "material_class")
    core_members = _core_members(class_map_path)

    zip_prices = _read_price_file(price_root / "home_depot_material_price_by_zip.csv").join(
        asset_geography,
        on="zip_code",
        how="inner",
    ).with_columns(
        pl.lit(1).alias("fallback_rank"),
        pl.lit("zip").alias("price_geography_level"),
        pl.col("zip_code").alias("price_geography_id"),
    )
    cbsa_prices = _read_price_file(
        price_root / "home_depot_material_price_by_cbsa.csv"
    ).join(asset_geography, on="cbsa_code", how="inner").with_columns(
        pl.lit(2).alias("fallback_rank"),
        pl.lit("cbsa").alias("price_geography_level"),
        pl.col("cbsa_code").alias("price_geography_id"),
    )
    state_prices = _read_price_file(
        price_root / "home_depot_material_price_by_state.csv"
    ).rename({"state": "state_code"}).join(
        asset_geography, on="state_code", how="inner"
    ).with_columns(
        pl.lit(3).alias("fallback_rank"),
        pl.lit("state").alias("price_geography_level"),
        pl.col("state_code").alias("price_geography_id"),
    )
    national_prices = _read_price_file(
        price_root / "home_depot_material_price_national.csv"
    ).join(asset_geography.select("asset_id"), how="cross").with_columns(
        pl.lit(4).alias("fallback_rank"),
        pl.lit("national").alias("price_geography_level"),
        pl.lit("US").alias("price_geography_id"),
    )
    selected = (
        pl.concat(
            [zip_prices, cbsa_prices, state_prices, national_prices],
            how="diagonal_relaxed",
        )
        .join(source_map, left_on="material_class", right_on="source_value", how="inner")
        .sort(["asset_id", "canonical_id", "fallback_rank"])
        .unique(subset=["asset_id", "canonical_id"], keep="first", maintain_order=True)
        .select(
            "asset_id",
            "canonical_id",
            "median_price_per_square",
            "scrape_date",
            "retailer",
            "fallback_rank",
            "price_geography_level",
            "price_geography_id",
        )
    )
    member_matrix = (
        asset_geography.select("asset_id")
        .join(core_members, how="cross")
        .join(selected, on=["asset_id", "canonical_id"], how="left", validate="1:1")
    )
    return (
        member_matrix.group_by("asset_id", "official_material_id")
        .agg(
            pl.col("median_price_per_square").mean().alias(
                "source_material_2026_usd_per_square"
            ),
            pl.col("canonical_id")
            .filter(pl.col("median_price_per_square").is_not_null())
            .sort()
            .alias("contributing_canonical_ids"),
            pl.col("canonical_id")
            .filter(pl.col("median_price_per_square").is_null())
            .sort()
            .alias("missing_member_ids"),
            pl.col("price_geography_level")
            .filter(pl.col("median_price_per_square").is_not_null())
            .alias("member_price_geography_levels"),
            pl.col("fallback_rank").max().alias("maximum_fallback_rank"),
            pl.col("scrape_date").drop_nulls().first(),
            pl.col("retailer").drop_nulls().first(),
        )
        .with_columns(
            (
                pl.col("source_material_2026_usd_per_square") / 100.0
            ).alias("source_material_2026_usd_per_sqft"),
            pl.col("missing_member_ids").list.len().alias("missing_member_count"),
            pl.col("contributing_canonical_ids").list.len().alias("contributor_count"),
        )
        .with_columns(
            pl.when(pl.col("contributor_count") == 0)
            .then(pl.lit("blocked_without_override"))
            .when(pl.col("missing_member_count") > 0)
            .then(pl.lit("partial_source_coverage"))
            .otherwise(pl.lit("complete_source_coverage"))
            .alias("material_price_status"),
            pl.lit("v1.0.0").alias("mapping_version"),
        )
        .sort(["asset_id", "official_material_id"])
    )


def build_material_growth_lookup(
    escalation_path: Path,
    mapping_path: Path,
    class_map_path: Path,
) -> pl.DataFrame:
    """Build annual cumulative real material growth factors by official class."""
    source_map = _domain_source_map(
        mapping_path, "material_escalation", "material_class"
    )
    core_members = _core_members(class_map_path)
    rates = pl.read_csv(escalation_path).join(
        source_map, left_on="material_class", right_on="source_value", how="inner"
    )
    classes = (
        core_members.join(rates, on="canonical_id", how="left", validate="1:1")
        .group_by("official_material_id")
        .agg(
            pl.col("annual_escalation_factor").mean(),
            pl.col("canonical_id")
            .filter(pl.col("annual_escalation_factor").is_null())
            .sort()
            .alias("missing_growth_member_ids"),
            pl.col("series_id").drop_nulls().unique().sort().alias("series_ids"),
        )
    )
    years = pl.DataFrame(
        {"year": pl.int_range(START_YEAR, END_YEAR + 1, eager=True)}
    )
    return classes.join(years, how="cross").with_columns(
        pl.col("annual_escalation_factor")
        .pow(pl.col("year") - START_YEAR)
        .alias("material_growth_factor"),
        pl.col("missing_growth_member_ids").list.len().gt(0).alias(
            "material_growth_incomplete"
        ),
    ).sort(["official_material_id", "year"])


def build_material_mass_lookup(
    mass_path: Path,
    mapping_path: Path,
    class_map_path: Path,
) -> pl.DataFrame:
    """Apply approved shared values and consolidate class mass in pounds per sqft."""
    source_map = _domain_source_map(mapping_path, "material_mass", "asset_class")
    core_members = _core_members(class_map_path)
    mapped = source_map.join(
        pl.read_csv(mass_path), left_on="source_value", right_on="asset_class", how="left"
    )
    result = core_members.join(mapped, on="canonical_id", how="left", validate="1:1")
    if result.filter(pl.col("weight_per_square_lbs").is_null()).height:
        raise ValueError("material mass mapping does not resolve every core member")
    return result.group_by("official_material_id").agg(
        pl.col("weight_per_square_lbs").mean(),
        pl.col("weight_per_sqft_lbs").mean(),
        pl.col("canonical_id").sort().alias("contributing_canonical_ids"),
        pl.col("relationship")
        .is_in(["shared_bucket", "candidate_shared_bucket"])
        .any()
        .alias("shared_mass_value_applied"),
    ).sort("official_material_id")


def build_physical_service_life_lookup(
    mass_path: Path,
    mapping_path: Path,
    class_map_path: Path,
) -> pl.DataFrame:
    """Consolidate approved physical service lives by official material class."""
    source_map = _domain_source_map(mapping_path, "material_mass", "asset_class")
    core_members = _core_members(class_map_path)
    mapped = source_map.join(
        pl.read_csv(mass_path), left_on="source_value", right_on="asset_class", how="left"
    )
    members = core_members.join(mapped, on="canonical_id", how="left", validate="1:1")
    if members.filter(pl.col("typical_service_life_years").is_null()).height:
        raise ValueError("physical service life mapping does not resolve every core member")
    return (
        members.group_by("official_material_id")
        .agg(
            pl.col("typical_service_life_years").mean().alias(
                "raw_physical_eul_years"
            ),
            pl.col("canonical_id").sort().alias("contributing_canonical_ids"),
            pl.col("relationship")
            .is_in(["shared_bucket", "candidate_shared_bucket"])
            .any()
            .alias("shared_service_life_value_applied"),
        )
        .with_columns(
            pl.col("raw_physical_eul_years")
            .round(0, mode="half_away_from_zero")
            .cast(pl.Int64)
            .alias("applied_physical_eul_years"),
            pl.lit("v1.0.0").alias("mapping_version"),
        )
        .sort("official_material_id")
    )


def _read_price_file(path: Path) -> pl.DataFrame:
    schema = {
        "zip_code": pl.String,
        "cbsa_code": pl.String,
        "state": pl.String,
    }
    frame = pl.read_csv(path, schema_overrides=schema)
    expressions = []
    if "zip_code" in frame.columns:
        expressions.append(pl.col("zip_code").str.zfill(5))
    if "cbsa_code" in frame.columns:
        expressions.append(pl.col("cbsa_code").str.zfill(5))
    return frame.with_columns(expressions)


def _domain_source_map(
    mapping_path: Path,
    domain: str,
    source_column: str,
) -> pl.DataFrame:
    mapping = pl.read_csv(mapping_path)
    selected = mapping.filter(
        (pl.col("mapping_domain") == "roof_material")
        & (pl.col("source_dataset_id") == domain)
        & (pl.col("source_column") == source_column)
        & pl.col("mapping_status").str.starts_with("approved")
    ).select("source_value", "canonical_id", "relationship", "confidence")
    if selected["canonical_id"].n_unique() != selected.height:
        raise ValueError(f"{domain} source map contains duplicate canonical IDs")
    return selected


def _core_members(class_map_path: Path) -> pl.DataFrame:
    members = pl.read_csv(class_map_path).filter(
        (pl.col("mapping_version") == "v1.0.0")
        & pl.col("aggregation_eligible")
    ).select(
        "canonical_id",
        pl.col("official_class_id").alias("official_material_id"),
    )
    found_classes = set(members["official_material_id"].to_list())
    if found_classes != set(OFFICIAL_MATERIAL_CLASSES):
        raise ValueError("class map must contain exactly three official material classes")
    return members


def _require_columns(frame: pl.DataFrame, columns: tuple, name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")