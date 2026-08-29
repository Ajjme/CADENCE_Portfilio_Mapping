"""Sequential lifecycle state for roof alternative analysis."""

from typing import List, Optional

import polars as pl

from cadence.economics.contracts import (
    AlternativeScenario,
    CostStream,
    EconomicsRunConfig,
    OFFICIAL_MATERIAL_CLASSES,
)

LIFECYCLE_ASSET_COLUMNS = (
    "asset_id",
    "official_current_material_id",
    "input_roof_age",
)
ANNUAL_OPTION_COLUMNS = (
    "asset_id",
    "year",
    "official_material_id",
    "roof_area_sqft",
    "installed_capex_usd",
    "operational_cost_source",
    "operational_cost_fallback_applied",
)
ANNUAL_DAMAGE_COLUMNS = (
    "asset_id",
    "year",
    "scenario_id",
    "expected_damage_ratio",
)
EVENT_COST_COLUMNS = (
    "asset_id",
    "year",
    "scenario_id",
    "event_disposal_cost_usd",
    "event_carbon_cost_usd",
)


def build_annual_scenario_state(
    assets: pl.DataFrame,
    service_lives: pl.DataFrame,
    config: EconomicsRunConfig,
) -> pl.DataFrame:
    """Build four independently aging roof scenarios for each asset and year."""
    _require_columns(assets, LIFECYCLE_ASSET_COLUMNS, "assets")
    _require_columns(
        service_lives,
        (
            "official_material_id",
            "raw_physical_eul_years",
            "applied_physical_eul_years",
            "mapping_version",
        ),
        "service_lives",
    )
    _validate_inputs(assets, service_lives)

    current_eul = (
        pl.col("current_roof_eul_years")
        if "current_roof_eul_years" in assets.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    scenarios = pl.DataFrame(
        {
            "scenario_id": [scenario.value for scenario in AlternativeScenario],
            "scenario_role": [
                "installed_baseline",
                "new_alternative",
                "new_alternative",
                "new_alternative",
            ],
            "alternative_material_id": [
                None,
                OFFICIAL_MATERIAL_CLASSES[0],
                OFFICIAL_MATERIAL_CLASSES[1],
                OFFICIAL_MATERIAL_CLASSES[2],
            ],
        }
    )
    state = (
        assets.with_columns(current_eul.alias("current_roof_eul_years"))
        .join(scenarios, how="cross")
        .with_columns(
            pl.when(pl.col("scenario_role") == "installed_baseline")
            .then(pl.col("official_current_material_id"))
            .otherwise(pl.col("alternative_material_id"))
            .alias("scenario_material_id"),
            pl.when(pl.col("scenario_role") == "installed_baseline")
            .then(pl.col("input_roof_age"))
            .otherwise(pl.lit(0))
            .cast(pl.Int64)
            .alias("roof_age_years"),
            pl.lit(0).cast(pl.Int64).alias("install_sequence"),
        )
        .join(
            service_lives.select(
                pl.col("official_material_id").alias("scenario_material_id"),
                "raw_physical_eul_years",
                "applied_physical_eul_years",
                pl.col("mapping_version").alias("service_life_mapping_version"),
            ),
            on="scenario_material_id",
            how="left",
            validate="m:1",
        )
        .with_columns(
            pl.when(
                (pl.col("scenario_role") == "installed_baseline")
                & pl.col("current_roof_eul_years").is_not_null()
            )
            .then(pl.col("current_roof_eul_years").round(0, mode="half_away_from_zero"))
            .otherwise(pl.col("applied_physical_eul_years"))
            .cast(pl.Int64)
            .alias("applied_eul_years"),
            pl.when(
                (pl.col("scenario_role") == "installed_baseline")
                & pl.col("current_roof_eul_years").is_not_null()
            )
            .then(pl.lit("asset_current_roof_eul"))
            .otherwise(pl.lit("official_class_physical_default"))
            .alias("eul_source"),
        )
    )

    annual_rows: List[pl.DataFrame] = []
    for year in range(config.start_year, config.end_year + 1):
        is_initial_alternative = (
            (pl.lit(year) == config.start_year)
            & (pl.col("scenario_role") == "new_alternative")
        )
        is_burnout = pl.col("roof_age_years") >= pl.col("applied_eul_years")
        state = (
            state.with_columns(
                is_initial_alternative.alias("initial_installation_event"),
                is_burnout.alias("burnout_replacement_event"),
            )
            .with_columns(
                (
                    pl.col("initial_installation_event")
                    | pl.col("burnout_replacement_event")
                ).alias("installation_event"),
                pl.when(pl.col("initial_installation_event"))
                .then(pl.col("official_current_material_id"))
                .when(pl.col("burnout_replacement_event"))
                .then(pl.col("scenario_material_id"))
                .otherwise(pl.lit(None, dtype=pl.String))
                .alias("removed_material_id"),
            )
            .with_columns(
                pl.when(pl.col("installation_event"))
                .then(pl.lit(0))
                .otherwise(pl.col("roof_age_years"))
                .cast(pl.Int64)
                .alias("roof_age_years"),
                pl.when(pl.col("burnout_replacement_event"))
                .then(pl.col("applied_physical_eul_years"))
                .otherwise(pl.col("applied_eul_years"))
                .cast(pl.Int64)
                .alias("applied_eul_years"),
                pl.when(pl.col("burnout_replacement_event"))
                .then(pl.lit("official_class_physical_default"))
                .otherwise(pl.col("eul_source"))
                .alias("eul_source"),
                (
                    pl.col("install_sequence")
                    + pl.col("installation_event").cast(pl.Int64)
                ).alias("install_sequence"),
            )
            .with_columns(
                pl.lit(year).alias("year"),
                (pl.col("roof_age_years") + 1)
                .clip(1, 30)
                .alias("lookup_roof_age"),
                (pl.col("roof_age_years") + 1 > 30).alias("age_capped"),
                (pl.col("applied_eul_years") - pl.col("roof_age_years")).alias(
                    "remaining_useful_life_years"
                ),
            )
        )
        annual_rows.append(state)
        state = state.with_columns(
            (pl.col("roof_age_years") + 1).alias("roof_age_years")
        ).drop(
            "year",
            "lookup_roof_age",
            "age_capped",
            "remaining_useful_life_years",
            "initial_installation_event",
            "burnout_replacement_event",
            "installation_event",
            "removed_material_id",
        )

    return pl.concat(annual_rows, how="vertical").sort(
        ["asset_id", "year", "scenario_id"]
    )


def build_annual_alternative_economics(
    annual_state: pl.DataFrame,
    annual_damage: pl.DataFrame,
    annual_option_costs: pl.DataFrame,
    config: EconomicsRunConfig,
    event_costs: Optional[pl.DataFrame] = None,
) -> pl.DataFrame:
    """Calculate annual climate risk, avoided damage, and lifecycle net benefit."""
    _require_columns(
        annual_state,
        (
            "asset_id",
            "year",
            "scenario_id",
            "scenario_role",
            "scenario_material_id",
            "installation_event",
        ),
        "annual_state",
    )
    _require_columns(annual_damage, ANNUAL_DAMAGE_COLUMNS, "annual_damage")
    _require_columns(annual_option_costs, ANNUAL_OPTION_COLUMNS, "annual_option_costs")
    _validate_four_scenarios(annual_state)

    option_columns = list(ANNUAL_OPTION_COLUMNS)
    if "expected_loss_of_use_usd" in annual_option_costs.columns:
        option_columns.append("expected_loss_of_use_usd")
    result = (
        annual_state.join(
            annual_damage.select(ANNUAL_DAMAGE_COLUMNS),
            on=["asset_id", "year", "scenario_id"],
            how="left",
            validate="1:1",
        )
        .join(
            annual_option_costs.select(option_columns),
            left_on=["asset_id", "year", "scenario_material_id"],
            right_on=["asset_id", "year", "official_material_id"],
            how="left",
            validate="m:1",
        )
    )
    if "expected_loss_of_use_usd" not in result.columns:
        result = result.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("expected_loss_of_use_usd")
        )
    result = result.with_columns(
        pl.col("installed_capex_usd").alias("active_installed_capex_usd"),
        pl.col("operational_cost_source").alias("active_cost_source"),
        pl.col("operational_cost_fallback_applied").alias(
            "active_cost_fallback_applied"
        ),
    ).with_columns(
        (
            pl.col("active_installed_capex_usd")
            * pl.col("expected_damage_ratio")
        ).alias("annual_repair_cost_usd"),
        pl.col("expected_damage_ratio").is_null().alias("repair_cost_incomplete"),
    )

    loss_enabled = CostStream.LOSS_OF_USE in config.enabled_cost_streams
    if loss_enabled:
        result = result.with_columns(
            (
                pl.col("annual_repair_cost_usd")
                + pl.col("expected_loss_of_use_usd")
            ).alias("annual_climate_risk_cost_usd"),
            (
                pl.col("annual_repair_cost_usd").is_null()
                | pl.col("expected_loss_of_use_usd").is_null()
            ).alias("climate_risk_total_incomplete"),
        )
    else:
        result = result.with_columns(
            pl.col("annual_repair_cost_usd").alias("annual_climate_risk_cost_usd"),
            pl.col("annual_repair_cost_usd")
            .is_null()
            .alias("climate_risk_total_incomplete"),
        )

    if event_costs is not None:
        _require_columns(event_costs, EVENT_COST_COLUMNS, "event_costs")
        result = result.join(
            event_costs.select(EVENT_COST_COLUMNS),
            on=["asset_id", "year", "scenario_id"],
            how="left",
            validate="1:1",
        )
    else:
        result = result.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("event_disposal_cost_usd"),
            pl.lit(None, dtype=pl.Float64).alias("event_carbon_cost_usd"),
        )

    result = result.with_columns(
        pl.when(pl.col("installation_event"))
        .then(pl.col("active_installed_capex_usd"))
        .otherwise(pl.lit(0.0))
        .alias("installation_event_capex_usd"),
        _event_stream_cost(
            CostStream.DISPOSAL,
            "event_disposal_cost_usd",
            config,
        ).alias("enabled_event_disposal_cost_usd"),
        _event_stream_cost(
            CostStream.CARBON,
            "event_carbon_cost_usd",
            config,
        ).alias("enabled_event_carbon_cost_usd"),
    ).with_columns(
        (
            pl.col("annual_climate_risk_cost_usd")
            + pl.col("installation_event_capex_usd")
            + pl.col("enabled_event_disposal_cost_usd")
            + pl.col("enabled_event_carbon_cost_usd")
        ).alias("annual_lifecycle_cash_flow_usd"),
        (
            pl.col("installation_event")
            & (
                pl.col("enabled_event_disposal_cost_usd").is_null()
                | pl.col("enabled_event_carbon_cost_usd").is_null()
            )
        ).alias("event_cost_incomplete"),
    )

    baseline = result.filter(
        pl.col("scenario_id") == AlternativeScenario.BASELINE_CURRENT.value
    ).select(
        "asset_id",
        "year",
        pl.col("annual_climate_risk_cost_usd").alias(
            "baseline_climate_risk_cost_usd"
        ),
        pl.col("annual_lifecycle_cash_flow_usd").alias(
            "baseline_lifecycle_cash_flow_usd"
        ),
    )
    result = result.join(
        baseline, on=["asset_id", "year"], how="left", validate="m:1"
    ).with_columns(
        (
            pl.col("baseline_climate_risk_cost_usd")
            - pl.col("annual_climate_risk_cost_usd")
        ).alias("annual_avoided_damage_usd"),
        (
            pl.col("baseline_lifecycle_cash_flow_usd")
            - pl.col("annual_lifecycle_cash_flow_usd")
        ).alias("annual_net_benefit_usd"),
        (1.0 / (1.0 + config.real_discount_rate) ** (pl.col("year") - config.start_year)).alias(
            "discount_factor"
        ),
    ).with_columns(
        (
            pl.col("annual_avoided_damage_usd") * pl.col("discount_factor")
        ).alias("discounted_annual_avoided_damage_usd"),
        (
            pl.col("annual_net_benefit_usd") * pl.col("discount_factor")
        ).alias("discounted_annual_net_benefit_usd"),
    ).sort(["asset_id", "scenario_id", "year"])
    window = ["asset_id", "scenario_id"]
    return result.with_columns(
        pl.col("annual_avoided_damage_usd")
        .cum_sum()
        .over(window)
        .alias("cumulative_avoided_damage_usd"),
        pl.col("discounted_annual_avoided_damage_usd")
        .cum_sum()
        .over(window)
        .alias("cumulative_discounted_avoided_damage_usd"),
        pl.col("annual_net_benefit_usd")
        .cum_sum()
        .over(window)
        .alias("cumulative_net_benefit_usd"),
        pl.col("discounted_annual_net_benefit_usd")
        .cum_sum()
        .over(window)
        .alias("net_present_value_usd"),
        pl.lit("real_2026_usd").alias("dollar_basis"),
    ).sort(["asset_id", "year", "scenario_id"])


def _validate_inputs(assets: pl.DataFrame, service_lives: pl.DataFrame) -> None:
    if assets["asset_id"].n_unique() != assets.height:
        raise ValueError("assets must contain unique asset_id values")
    if assets.filter(pl.col("input_roof_age") < 1).height:
        raise ValueError("input_roof_age must be a positive integer")
    invalid_materials = assets.filter(
        ~pl.col("official_current_material_id").is_in(OFFICIAL_MATERIAL_CLASSES)
    )
    if invalid_materials.height:
        raise ValueError("official_current_material_id contains an unsupported class")
    if set(service_lives["official_material_id"].to_list()) != set(
        OFFICIAL_MATERIAL_CLASSES
    ):
        raise ValueError("service_lives must contain exactly three official classes")
    if service_lives.filter(pl.col("applied_physical_eul_years") <= 0).height:
        raise ValueError("physical service lives must be positive")


def _validate_four_scenarios(annual_state: pl.DataFrame) -> None:
    expected = {scenario.value for scenario in AlternativeScenario}
    groups = annual_state.group_by("asset_id", "year").agg(
        pl.len().alias("row_count"),
        pl.col("scenario_id").n_unique().alias("scenario_count"),
        pl.col("scenario_id").alias("scenarios"),
    )
    invalid = groups.filter(
        (pl.col("row_count") != len(expected))
        | (pl.col("scenario_count") != len(expected))
    )
    if invalid.height or any(set(values) != expected for values in groups["scenarios"]):
        raise ValueError("every asset-year must contain exactly four lifecycle scenarios")


def _event_stream_cost(
    stream: CostStream,
    column: str,
    config: EconomicsRunConfig,
) -> pl.Expr:
    if stream not in config.enabled_cost_streams:
        return pl.lit(0.0)
    return pl.when(pl.col("installation_event")).then(pl.col(column)).otherwise(0.0)


def _require_columns(frame: pl.DataFrame, columns: tuple, name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")