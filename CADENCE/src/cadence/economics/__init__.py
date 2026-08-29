"""Public API for CADENCE roof economics calculations."""

from cadence.economics.contracts import (
    AlternativeScenario,
    AssetEconomicsInput,
    CostStream,
    EconomicsRunConfig,
    InstalledCostOverride,
)
from cadence.economics.alternative_analysis import (
    build_annual_alternative_economics,
    build_annual_scenario_state,
)
from cadence.economics.costs import build_annual_roof_option_costs
from cadence.economics.pipeline import run_economics_pipeline
from cadence.economics.alternative_pipeline import run_alternative_analysis_pipeline

__all__ = [
    "AlternativeScenario",
    "AssetEconomicsInput",
    "build_annual_roof_option_costs",
    "build_annual_alternative_economics",
    "build_annual_scenario_state",
    "CostStream",
    "EconomicsRunConfig",
    "InstalledCostOverride",
    "run_economics_pipeline",
    "run_alternative_analysis_pipeline",
]