"""The shapes of what the API sends and receives.

FastAPI checks every response against these models and lists them on the /docs
page. The frontend's TypeScript types are generated from them too, so a change
here shows up as a type error in the React code.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Material and labor are always counted. These are the cost streams a user can turn on.
OptionalCostStream = Literal["disposal", "carbon"]


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class SettingsChoices(BaseModel):
    """Default run settings, plus the values each one is allowed to take."""

    start_year: int
    end_year: int
    real_discount_rate: float = Field(description="Annual real discount rate, as a fraction (0.02 = 2%)")
    scghg_discount_rate: float = Field(description="Social cost of carbon rate, in percent")
    demand_surge: bool
    cost_streams: list[OptionalCostStream] = Field(description="Optional cost streams that are on by default")
    first_year: int
    last_year: int
    scghg_discount_rate_options: list[float]
    optional_cost_streams: list[OptionalCostStream]
    metrics: dict[str, str] = Field(description="Yearly result columns and their labels")


class Portfolio(BaseModel):
    """A validated asset workbook."""

    workbook_id: str = Field(description='"default" for the example workbook, otherwise the uploaded file\'s ID')
    file_name: str
    asset_count: int
    assets: list[dict[str, Any]] = Field(description="One row per asset, with the workbook's columns")


class RunSettings(BaseModel):
    """Settings for one run. Anything left out uses the default."""

    start_year: Optional[int] = None
    end_year: Optional[int] = None
    real_discount_rate: Optional[float] = Field(default=None, ge=0)
    scghg_discount_rate: Optional[float] = None
    demand_surge: Optional[bool] = None
    cost_streams: Optional[list[OptionalCostStream]] = Field(
        default=None, description="Optional cost streams to turn on. Material and labor are always on."
    )


class RunRequest(BaseModel):
    workbook_id: str = Field(default="default", description='From POST /api/portfolio, or "default"')
    asset_ids: Optional[list[str]] = Field(default=None, description="Run only these assets. Leave out to run all of them.")
    settings: RunSettings = Field(default_factory=RunSettings)


class RunInfo(BaseModel):
    run_id: str
    schema_version: str
    run_timestamp: Optional[str] = None
    asset_count: int
    start_year: int
    end_year: int
    real_discount_rate: Optional[float] = None
    scghg_discount_rate: Optional[float] = None
    demand_surge: Optional[bool] = None
    enabled_cost_streams: list[str]
    dollar_basis: Optional[str] = None
    market_study_ready: bool = Field(
        default=False,
        description="True when the backend has the asset inputs the Market Study needs for this run",
    )


class PortfolioScenario(BaseModel):
    """Totals across all assets for one replacement option. A total is null when any asset is missing a value."""

    scenario_id: str
    asset_count: int
    burnout_replacement_count: Optional[float] = None
    cumulative_avoided_damage_usd: Optional[float] = None
    cumulative_discounted_avoided_damage_usd: Optional[float] = None
    cumulative_net_benefit_usd: Optional[float] = None
    net_present_value_usd: Optional[float] = None
    active_cost_fallback_applied: bool
    repair_cost_incomplete: bool
    climate_risk_total_incomplete: bool
    event_cost_incomplete: bool


class AssetScenario(BaseModel):
    """Final results for one asset and replacement option."""

    asset_id: str
    scenario_id: str
    scenario_material_id: Optional[str] = None
    through_year: Optional[int] = None
    cumulative_avoided_damage_usd: Optional[float] = None
    cumulative_discounted_avoided_damage_usd: Optional[float] = None
    cumulative_net_benefit_usd: Optional[float] = None
    net_present_value_usd: Optional[float] = None
    burnout_replacement_count: Optional[float] = None
    active_cost_source: Optional[str] = None
    active_cost_fallback_applied: Optional[bool] = None
    repair_cost_incomplete: Optional[bool] = None
    climate_risk_total_incomplete: Optional[bool] = None
    event_cost_incomplete: Optional[bool] = None


class RunSummary(BaseModel):
    run_id: str
    portfolio: list[PortfolioScenario]
    assets: list[AssetScenario]


class SeriesPoint(BaseModel):
    year: int
    scenario_id: str
    value: Optional[float] = Field(description="Null when an asset is missing a value that year")
    installation_events: int
    replacement_events: int


class Series(BaseModel):
    run_id: str
    asset_id: Optional[str] = Field(description="Null for the whole portfolio")
    metric: str
    label: str
    points: list[SeriesPoint]


class CostAllocation(BaseModel):
    """One replacement option's costs in one year, split into parts. A part is null when it can't be split."""

    scenario_id: str
    material_usd: Optional[float] = None
    labor_usd: Optional[float] = None
    repair_usd: Optional[float] = None
    loss_of_use_usd: Optional[float] = None
    disposal_usd: Optional[float] = None
    carbon_usd: Optional[float] = None
    total_usd: Optional[float] = None
    allocation_estimated: bool = Field(description="True when the material and labor split uses default shares")


class CostAllocations(BaseModel):
    run_id: str
    asset_id: Optional[str] = Field(description="Null for the whole portfolio")
    year: int
    labels: dict[str, str] = Field(description="Cost columns and their labels, in chart order")
    rows: list[CostAllocation]


class MarketStudyRequest(BaseModel):
    max_payback_years: Optional[int] = Field(
        default=None,
        ge=1,
        description="Longest payback a homeowner accepts for a voluntary replacement. Leave out for no limit.",
    )


class RoofShare(BaseModel):
    """How many roofs of one material the portfolio has in one year, after that year's replacements."""

    year: int
    material_id: str = Field(description="OFFICIAL_ASPHALT, OFFICIAL_METAL, OFFICIAL_TILE, or UNKNOWN")
    asset_count: int
    share_percent: float


class MarketYear(BaseModel):
    """The portfolio's expected costs in one year, and how many roofs were replaced and why."""

    year: int
    repair_usd: Optional[float] = None
    loss_of_use_usd: Optional[float] = None
    material_usd: Optional[float] = None
    labor_usd: Optional[float] = None
    disposal_usd: Optional[float] = None
    carbon_usd: Optional[float] = None
    total_usd: Optional[float] = Field(default=None, description="Null when an asset's costs are incomplete")
    replacement_count: int
    eul_replacements: int
    damage_replacements: int
    economic_replacements: int
    unknown_count: int


class MarketStudy(BaseModel):
    """An experimental study of which roofs a homeowner would replace each year, and when."""

    run_id: str = Field(description="The Alternative Analysis run the study is based on")
    study_id: str
    max_payback_years: Optional[int] = None
    newly_calculated: bool = Field(description="False when an earlier study with the same settings was reused")
    asset_count: int
    last_verified_year: int = Field(description="The run's last year. Later years hold prices and climate constant")
    evaluation_end_year: int
    real_discount_rate: float
    enabled_cost_streams: list[str]
    tile_uses_metal_proxy: bool
    policy_id: str
    cost_labels: dict[str, str] = Field(description="Cost columns and their labels, in chart order")
    roof_share: list[RoofShare]
    costs: list[MarketYear]
