"""Annual-loss planning proxy for wind roof insurance underwriting."""

from __future__ import annotations

from typing import Optional

import polars as pl
from pydantic import BaseModel

from cadence.insurance.contracts import POLICY_COLUMNS

SCENARIOS = {"BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE"}


class AnnualInsuranceRecord(BaseModel):
    asset_id: str
    year: int
    scenario_id: str
    annual_repair_cost_usd: Optional[float]
    insured_value: Optional[float]
    policy_id: Optional[str]
    deductible_amount: Optional[float]
    deductible_type: Optional[str]
    peril: Optional[str]
    current_premium: Optional[float]
    policy_issue: Optional[str]
    insurance_issue: Optional[str]
    premium_usd: Optional[float]
    expected_payout_usd: Optional[float]
    underwriting_margin_usd: Optional[float]
    loss_ratio: Optional[float]
    cumulative_premium_usd: Optional[float]
    cumulative_payout_usd: Optional[float]
    cumulative_margin_usd: Optional[float]


ANNUAL_COLUMNS = tuple(AnnualInsuranceRecord.model_fields)


def calculate_insurance(annual: pl.DataFrame, policies: pl.DataFrame) -> pl.DataFrame:
    """Overlay per-asset terms on expected annual repair, never individual claims."""
    required = {"asset_id", "year", "scenario_id", "annual_repair_cost_usd"}
    if required - set(annual.columns) or set(POLICY_COLUMNS) - set(policies.columns):
        raise ValueError("insurance inputs are missing required columns")
    if annual.is_empty() or policies.is_empty():
        raise ValueError("insurance requires nonempty annual results and policies")
    if annual.unique(["asset_id", "year", "scenario_id"]).height != annual.height:
        raise ValueError("annual insurance results have duplicate asset/year/scenario rows")
    if policies["asset_id"].n_unique() != policies.height:
        raise ValueError("insurance policies have duplicate asset IDs")
    if set(annual["asset_id"].unique().to_list()) != set(policies["asset_id"].to_list()):
        raise ValueError("policy asset IDs do not match the selected alternative run")
    groups = annual.group_by("asset_id", "year").agg(
        pl.col("scenario_id").sort().alias("scenarios")
    )
    if groups.filter(pl.col("scenarios") != sorted(SCENARIOS)).height:
        raise ValueError("each asset/year requires the installed roof and three alternatives")
    if annual.filter(
        pl.col("annual_repair_cost_usd").is_not_null()
        & (~pl.col("annual_repair_cost_usd").is_finite() | (pl.col("annual_repair_cost_usd") < 0))
    ).height:
        raise ValueError("annual repair cost must be nonnegative and finite when present")

    result = annual.select(sorted(required)).join(
        policies.select(POLICY_COLUMNS), on="asset_id", how="left", validate="m:1"
    ).sort(["asset_id", "scenario_id", "year"])
    result = result.with_columns(
        pl.coalesce(
            pl.col("policy_issue"),
            pl.when(pl.col("annual_repair_cost_usd").is_null())
            .then(pl.lit("Expected repair cost unavailable")),
        ).alias("insurance_issue")
    )
    complete = pl.col("insurance_issue").is_null()
    result = result.with_columns(
        pl.when(complete).then(pl.col("current_premium")).alias("premium_usd"),
        pl.when(complete)
        .then(
            (pl.col("annual_repair_cost_usd") - pl.col("deductible_amount"))
            .clip(lower_bound=0)
            .clip(upper_bound=pl.col("insured_value"))
        ).alias("expected_payout_usd"),
    ).with_columns(
        (pl.col("premium_usd") - pl.col("expected_payout_usd"))
        .alias("underwriting_margin_usd"),
        pl.when(pl.col("premium_usd") > 0)
        .then(pl.col("expected_payout_usd") / pl.col("premium_usd"))
        .alias("loss_ratio"),
    )
    window = ["asset_id", "scenario_id"]
    result = result.with_columns(
        *(
            pl.when(complete.cast(pl.Int8).cum_min().over(window) == 1)
            .then(pl.col(column).fill_null(0).cum_sum().over(window))
            .alias(cumulative)
            for column, cumulative in (
                ("premium_usd", "cumulative_premium_usd"),
                ("expected_payout_usd", "cumulative_payout_usd"),
                ("underwriting_margin_usd", "cumulative_margin_usd"),
            )
        )
    )
    return result.select(ANNUAL_COLUMNS).sort(["asset_id", "year", "scenario_id"])