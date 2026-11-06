"""Scheduled roof comparisons and one-time economic break-even grants."""

from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import polars as pl

from cadence.economics.alternative_analysis import build_annual_alternative_economics
from cadence.economics.contracts import CostStream, EconomicsRunConfig
from cadence.program.contracts import (
    COMPONENTS, COUNTERFACTUALS, TARGETS, ProgramInputs, damage_state,
)
from cadence.vulnerability.annual_damage import build_annual_scenario_damage


def evaluate(inputs: ProgramInputs) -> Tuple[pl.DataFrame, pl.DataFrame]:
    """Return candidate summaries and full-horizon physical/cash-flow audits."""
    frames = []
    for year in range(inputs.config.start_year, inputs.config.end_year + 1):
        state = inputs.states.filter(pl.col("candidate_year") == year)
        damage = build_annual_scenario_damage(
            damage_state(state, bool(inputs.metadata.get("temporary_tile_policy"))),
            inputs.hazard, Path("."), inputs.climate, curves=inputs.curves,
        )
        events = state.join(
            inputs.removal_costs,
            left_on=["asset_id", "year", "removed_material_id"],
            right_on=["asset_id", "year", "official_material_id"],
            how="left", validate="m:1",
        ).select(
            "asset_id", "year", "scenario_id",
            pl.col("disposal_cost_usd").alias("event_disposal_cost_usd"),
            pl.col("carbon_cost_usd").alias("event_carbon_cost_usd"),
        )
        annual = build_annual_alternative_economics(
            state, damage, inputs.option_costs, inputs.config, event_costs=events,
        ).with_columns(
            (pl.col("expected_loss_of_use_usd")
             if CostStream.LOSS_OF_USE in inputs.config.enabled_cost_streams
             else pl.lit(0.0)).alias("enabled_loss_of_use_usd"),
        )
        frames.append(annual)
    annual = pl.concat(frames, how="vertical")
    return summarize(annual, inputs.config), annual


def _sum_complete(values: List[Optional[float]]) -> Optional[float]:
    if any(value is None or not isfinite(value) for value in values):
        return None
    total = sum(value for value in values if value is not None)
    return total if isfinite(total) else None


def summarize(annual: pl.DataFrame, config: EconomicsRunConfig) -> pl.DataFrame:
    """Calculate each counterfactual independently; never sum candidate choices."""
    required = {
        "asset_id", "candidate_year", "year", "scenario_id",
        "official_current_material_id", *COMPONENTS.values(),
    }
    if required - set(annual.columns):
        raise ValueError("Program annual results are missing required columns")
    keys = ["asset_id", "candidate_year", "year", "scenario_id"]
    if annual.unique(keys).height != annual.height:
        raise ValueError("Program annual results have duplicate keys")
    if annual["asset_id"].n_unique() != 1:
        raise ValueError("Program analysis requires exactly one home")
    years = list(range(config.start_year, config.end_year + 1))
    expected = {(y, t, s) for y in years for t in years for s in ("BASELINE_CURRENT", *TARGETS)}
    if set(annual.select(keys[1:]).iter_rows()) != expected:
        raise ValueError("Program annual results do not cover every candidate, year, and scenario")
    if not isfinite(config.real_discount_rate):
        raise ValueError("Program discount rate must be finite")
    for field in COMPONENTS.values():
        if annual.filter(pl.col(field).is_not_null() & (
            ~pl.col(field).is_finite() | (pl.col(field) < 0)
        )).height:
            raise ValueError(f"Program costs must be finite and nonnegative: {field}")
    records: List[Dict] = []
    for candidate_year in years:
        subset = annual.filter(
            (pl.col("candidate_year") == candidate_year) & (pl.col("year") >= candidate_year)
        )
        current = subset["official_current_material_id"].unique().to_list()
        if len(current) != 1 or current[0].replace("OFFICIAL_", "NEW_") not in TARGETS:
            raise ValueError("Program conventional material is invalid")
        conventional = current[0].replace("OFFICIAL_", "NEW_")
        paths = {
            scenario: subset.filter(pl.col("scenario_id") == scenario).sort("year").to_dicts()
            for scenario in ("BASELINE_CURRENT", *TARGETS)
        }
        for target in TARGETS:
            for comparison in COUNTERFACTUALS:
                base = paths["BASELINE_CURRENT" if comparison == "KEEP_TO_EOL" else conventional]
                upgrade = paths[target]
                row = {
                    "asset_id": upgrade[0]["asset_id"], "target_scenario": target,
                    "candidate_year": candidate_year, "counterfactual": comparison,
                    "same_material_renewal": target == conventional,
                    "recommended": False, "recommendation_provisional": False,
                    "dollar_basis": "real_2026_usd",
                }
                missing = []
                for component, field in COMPONENTS.items():
                    differences = [
                        None if b[field] is None or u[field] is None else
                        (b[field] - u[field]) * (1 + config.real_discount_rate) ** -(b["year"] - candidate_year)
                        for b, u in zip(base, upgrade)
                    ]
                    row[f"npv_{component}_usd"] = _sum_complete(differences)
                    if row[f"npv_{component}_usd"] is None:
                        missing.append(component)
                npv = _sum_complete([row[f"npv_{name}_usd"] for name in COMPONENTS])
                row["npv_at_installation_usd"] = npv
                row["npv_at_start_usd"] = (
                    npv * (1 + config.real_discount_rate) ** -(candidate_year - config.start_year)
                    if npv is not None else None
                )
                grant = max(0.0, -npv) if npv is not None else None
                row["economic_grant_usd"] = grant
                row["grant_adjusted_npv_usd"] = npv + grant if npv is not None and grant is not None else None
                for label, path in (("target", upgrade), ("comparator", base)):
                    row[f"{label}_upfront_usd"] = _sum_complete([
                        path[0][COMPONENTS["installation"]], path[0][COMPONENTS["disposal"]],
                    ])
                for component in ("installation", "disposal"):
                    b, u = base[0][COMPONENTS[component]], upgrade[0][COMPONENTS[component]]
                    row[f"current_{component}_benefit_usd"] = b - u if b is not None and u is not None else None
                target_cost, base_cost = row["target_upfront_usd"], row["comparator_upfront_usd"]
                difference = target_cost - base_cost if target_cost is not None and base_cost is not None else None
                row["signed_upfront_difference_usd"] = difference
                row["upfront_gap_usd"] = max(0.0, difference) if difference is not None else None
                row["unavailable_reason"] = f"Missing required costs: {', '.join(missing)}" if missing else None
                records.append(row)
    for target in TARGETS:
        for comparison in COUNTERFACTUALS:
            group = [r for r in records if r["target_scenario"] == target and r["counterfactual"] == comparison]
            valid = [r for r in group if r["economic_grant_usd"] is not None]
            if valid:
                best = min(valid, key=lambda r: (
                    Decimal(str(r["economic_grant_usd"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    r["candidate_year"],
                ))
                best["recommended"] = True
            for row in group:
                row["recommendation_provisional"] = len(valid) != len(group)
    return pl.DataFrame(records, infer_schema_length=None).with_columns(
        pl.col("unavailable_reason").cast(pl.String),
        *(pl.col(name).cast(pl.Float64) for name in records[0] if name.endswith("_usd")),
    ).sort(["target_scenario", "counterfactual", "candidate_year"])
