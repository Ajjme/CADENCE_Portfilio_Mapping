"""Versioned, pre-insurance Program analysis contracts."""

from dataclasses import dataclass
from typing import Any, Dict

import polars as pl

from cadence.economics.contracts import EconomicsRunConfig

SCHEMA_VERSION = "v0.1.0"
FORMULA_VERSION = "pre_insurance_installation_year_grant_no_terminal_v1"
COUNTERFACTUALS = {
    "KEEP_TO_EOL": "Keep roof; replace in kind at useful life",
    "CONVENTIONAL_AT_YEAR": "New conventional roof in installation year",
}
TARGETS = ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
COMPONENTS = {
    "installation": "installation_event_capex_usd",
    "disposal": "enabled_event_disposal_cost_usd",
    "repair": "annual_repair_cost_usd",
    "loss_of_use": "enabled_loss_of_use_usd",
}
SNAPSHOTS = (
    "assets", "service_lives", "option_costs", "removal_costs",
    "hazard", "climate", "curves", "states",
)


@dataclass
class ProgramInputs:
    config: EconomicsRunConfig
    metadata: Dict[str, Any]
    assets: pl.DataFrame
    service_lives: pl.DataFrame
    option_costs: pl.DataFrame
    removal_costs: pl.DataFrame
    hazard: pl.DataFrame
    climate: pl.DataFrame
    curves: pl.DataFrame
    states: pl.DataFrame


def damage_state(state: pl.DataFrame, tile_proxy: bool) -> pl.DataFrame:
    """Keep the actual current roof vulnerability until the Tile intervention."""
    if not tile_proxy:
        return state
    return state.with_columns(
        pl.when(
            (pl.col("scenario_id") == "NEW_TILE")
            & (pl.col("year") >= pl.col("candidate_year"))
        ).then(pl.lit("OFFICIAL_METAL"))
        .otherwise(pl.col("scenario_material_id")).alias("scenario_material_id"),
    )
