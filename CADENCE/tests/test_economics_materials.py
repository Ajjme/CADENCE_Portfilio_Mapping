from pathlib import Path

import polars as pl
import pytest

from cadence.economics.materials import (
    build_material_growth_lookup,
    build_material_mass_lookup,
    build_material_price_lookup,
    build_physical_service_life_lookup,
)

MAPPING_ROOT = Path("Data_Catalogs/Mapping")


def test_material_prices_apply_geography_fallback_before_consolidation() -> None:
    assets = pl.DataFrame(
        {
            "asset_id": ["A-1"],
            "zip_code": ["77001"],
            "cbsa_code": ["26420"],
            "state_code": ["TX"],
        }
    )

    lookup = build_material_price_lookup(
        assets,
        Path("Data/Materials/Start_Year_2026"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    asphalt = lookup.filter(
        pl.col("official_material_id") == "OFFICIAL_ASPHALT"
    ).row(0, named=True)
    metal = lookup.filter(pl.col("official_material_id") == "OFFICIAL_METAL").row(
        0, named=True
    )
    tile = lookup.filter(pl.col("official_material_id") == "OFFICIAL_TILE").row(
        0, named=True
    )

    assert asphalt["source_material_2026_usd_per_sqft"] == pytest.approx(
        (116.92169216921693 + 128.92289228922894) / 2 / 100
    )
    assert asphalt["missing_member_ids"] == ["MAT_ASPHALT_PREMIUM_ARCH"]
    assert metal["maximum_fallback_rank"] == 4
    assert metal["member_price_geography_levels"] == ["national"]
    assert tile["source_material_2026_usd_per_sqft"] is None
    assert tile["material_price_status"] == "blocked_without_override"


def test_material_growth_starts_at_one_and_preserves_missing_metal_member() -> None:
    lookup = build_material_growth_lookup(
        Path("Data/Materials/Escalation/material_projection_rates.csv"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    metal_2026 = lookup.filter(
        (pl.col("official_material_id") == "OFFICIAL_METAL")
        & (pl.col("year") == 2026)
    ).row(0, named=True)
    metal_2027 = lookup.filter(
        (pl.col("official_material_id") == "OFFICIAL_METAL")
        & (pl.col("year") == 2027)
    ).row(0, named=True)

    assert metal_2026["material_growth_factor"] == 1.0
    assert metal_2027["material_growth_factor"] == pytest.approx(
        metal_2027["annual_escalation_factor"]
    )
    assert metal_2027["missing_growth_member_ids"] == ["MAT_METAL_ROOF_TILE"]


def test_material_mass_applies_shared_values_before_class_average() -> None:
    lookup = build_material_mass_lookup(
        Path("Data/Material_Mass/roofing_lbs.csv"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    values = {
        row["official_material_id"]: row
        for row in lookup.iter_rows(named=True)
    }

    assert values["OFFICIAL_ASPHALT"]["weight_per_sqft_lbs"] == pytest.approx(2.25)
    assert values["OFFICIAL_METAL"]["weight_per_sqft_lbs"] == pytest.approx(1.1)
    assert values["OFFICIAL_TILE"]["weight_per_sqft_lbs"] == pytest.approx(8.5)
    assert values["OFFICIAL_METAL"]["shared_mass_value_applied"] is True


def test_physical_service_life_applies_shared_values_and_rounds() -> None:
    lookup = build_physical_service_life_lookup(
        Path("Data/Material_Mass/roofing_lbs.csv"),
        MAPPING_ROOT / "master_mapping_reference_draft.csv",
        MAPPING_ROOT / "official_material_class_map_v1.csv",
    )
    values = {row["official_material_id"]: row for row in lookup.iter_rows(named=True)}

    assert values["OFFICIAL_ASPHALT"]["raw_physical_eul_years"] == pytest.approx(
        (17.5 + 27.5 + 27.5) / 3
    )
    assert values["OFFICIAL_ASPHALT"]["applied_physical_eul_years"] == 24
    assert values["OFFICIAL_METAL"]["applied_physical_eul_years"] == 55
    assert values["OFFICIAL_TILE"]["applied_physical_eul_years"] == 60