"""Validated inputs for the CADENCE roof economics pipeline."""

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

START_YEAR = 2026
END_YEAR = 2050
OFFICIAL_MATERIAL_CLASSES = (
    "OFFICIAL_ASPHALT",
    "OFFICIAL_METAL",
    "OFFICIAL_TILE",
)


class AlternativeScenario(str, Enum):
    """The four lifecycle scenarios evaluated for every asset."""

    BASELINE_CURRENT = "BASELINE_CURRENT"
    NEW_ASPHALT = "NEW_ASPHALT"
    NEW_METAL = "NEW_METAL"
    NEW_TILE = "NEW_TILE"


class CostStream(str, Enum):
    """Cost streams recognized by the first economics pipeline."""

    MATERIAL = "material"
    LABOR = "labor"
    DISPOSAL = "disposal"
    CARBON = "carbon"
    LOSS_OF_USE = "loss_of_use"


class InstalledCostOverride(BaseModel):
    """User-supplied installed cost and its fixed escalation blend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    installed_usd_per_sqft: float = Field(ge=0.0)
    material_share: float = Field(ge=0.0, le=1.0)
    labor_share: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_shares(self) -> "InstalledCostOverride":
        if abs(self.material_share + self.labor_share - 1.0) > 1e-9:
            raise ValueError("material_share and labor_share must sum to 1")
        return self


class AssetEconomicsInput(BaseModel):
    """Asset fields required by the ID-only economics runtime."""

    model_config = ConfigDict(extra="allow", frozen=True)

    asset_id: str = Field(min_length=1)
    current_roof_type: str = Field(min_length=1)
    roof_area_sqft: float = Field(gt=0.0)
    input_roof_age: int = Field(ge=1)
    current_roof_eul_years: Optional[float] = Field(default=None, gt=0.0)
    zip_code: str = Field(min_length=5, max_length=5)
    cbsa_code: str = Field(min_length=5, max_length=5)
    state_code: str = Field(min_length=2, max_length=2)
    county_fips: str = Field(min_length=5, max_length=5)
    labor_market_id: str = Field(min_length=1)
    roof_shape: Optional[str] = None
    roof_deck_attachment: Optional[str] = None
    roof_wall_connection: Optional[str] = None


class EconomicsRunConfig(BaseModel):
    """Validated economic assumptions for one reproducible run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_year: int = START_YEAR
    end_year: int = END_YEAR
    enabled_cost_streams: frozenset[CostStream] = frozenset(
        {CostStream.MATERIAL, CostStream.LABOR}
    )
    installed_cost_overrides: Dict[str, InstalledCostOverride]
    default_roof_shape: str = Field(min_length=1)
    default_roof_deck_attachment: str = Field(min_length=1)
    default_roof_wall_connection: str = Field(min_length=1)
    scghg_discount_rate: float = Field(default=2.0)
    real_discount_rate: float = Field(default=0.02, ge=0.0)
    operational_value_tolerance_percent: float = Field(default=20.0, ge=0.0)
    demand_surge: bool = False

    @model_validator(mode="after")
    def validate_locked_configuration(self) -> "EconomicsRunConfig":
        if not START_YEAR <= self.start_year <= self.end_year <= END_YEAR:
            raise ValueError("economics horizon must be within 2026 through 2050")
        override_classes = set(self.installed_cost_overrides)
        expected_classes = set(OFFICIAL_MATERIAL_CLASSES)
        if override_classes != expected_classes:
            raise ValueError(
                "installed_cost_overrides must contain exactly Asphalt, Metal, and Tile"
            )
        if self.scghg_discount_rate not in {1.5, 2.0, 2.5}:
            raise ValueError("scghg_discount_rate must be 1.5, 2.0, or 2.5")
        return self