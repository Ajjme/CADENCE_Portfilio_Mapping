"""Deterministic wind-roof event losses, independent of annual loss integration."""

from __future__ import annotations

from typing import Literal, Optional, Tuple

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, field_validator

from cadence.insurance.analysis import SCENARIOS
from cadence.reference_data.economics_assets import FIPS_TO_STATE

EventPeriod = Literal[100, 200, 300, 500]
EVENT_PERIODS: Tuple[EventPeriod, ...] = (100, 200, 300, 500)
EVENT_METRICS = ("gross_event_damage_usd", "insured_event_payout_usd")
LIMITATIONS = (
    "Deterministic local wind-return-level stress test, not a storm track, portfolio "
    "loss return period, or regulatory certification. Wind-roof repair only; building-loss "
    "curves are provisional roof/material proxies. NEW_TILE uses Metal vulnerability "
    "and adjusted installed cost; fragility lookup ages are capped at 30. The 300-year "
    "gust is estimated by log-return-period interpolation. Material and labor costs "
    "exclude tear-off labor. Flat per-asset deductibles and insured-value payout caps "
    "only; repeated policy IDs do not share terms. No hail, reinsurance, percentage "
    "deductibles, policy aggregates, or changes to future roof lifecycle states."
)


class EventSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int
    return_period: EventPeriod = 100
    states: Optional[Tuple[str, ...]] = None

    @field_validator("states")
    @classmethod
    def normalize_states(cls, value: Optional[Tuple[str, ...]]) -> Optional[Tuple[str, ...]]:
        if value is None:
            return None
        states = tuple(sorted({state.strip().upper() for state in value}))
        if not states or not set(states).issubset(set(FIPS_TO_STATE.values())):
            raise ValueError("select at least one valid state or choose All portfolio")
        return states


def calculate_event(
    inputs: pl.DataFrame, settings: EventSettings, curves: Optional[pl.DataFrame] = None,
) -> pl.DataFrame:
    """Apply one local wind event to each affected roof, then its own policy terms."""
    required = {
        "asset_id", "scenario_id", "year", "state_code", "active_installed_capex_usd",
        "policy_id", "insured_value", "deductible_amount", "deductible_type", "peril",
    }
    periods = (200, 500) if settings.return_period == 300 else (settings.return_period,)
    required.update(f"climate_scaled_rp_{period}_3sec_gust" for period in periods)
    if settings.return_period != 300:
        required.add(f"rp_{settings.return_period}_damage_ratio")
    missing = required - set(inputs.columns)
    if missing:
        raise ValueError(f"event inputs missing columns: {sorted(missing)}")
    if inputs.is_empty() or inputs["asset_id"].null_count():
        raise ValueError("event inputs require nonempty asset IDs")
    if inputs.unique(["asset_id", "scenario_id"]).height != inputs.height:
        raise ValueError("event inputs contain duplicate asset/scenario rows")
    if inputs["year"].null_count() or set(inputs["year"]) != {settings.year}:
        raise ValueError("event inputs do not match the selected year")
    for group in inputs.partition_by("asset_id"):
        if set(group["scenario_id"]) != SCENARIOS or group["state_code"].n_unique() != 1:
            raise ValueError("each asset requires four scenarios and a consistent state")
    if settings.states is not None:
        if any(state not in FIPS_TO_STATE.values() for state in inputs["state_code"]):
            raise ValueError("resolve unknown asset states before selecting a state footprint")
        if not inputs.filter(pl.col("state_code").is_in(settings.states)).height:
            raise ValueError("No assets are in the selected states")

    curve_lookup = {}
    if settings.return_period == 300:
        if curves is None or not {"asset_id", "scenario_id", "wind_speed_mph", "building_loss_ratio"}.issubset(curves.columns):
            raise ValueError("300-year events require verified effective fragility curves")
        for key, curve in curves.partition_by(["asset_id", "scenario_id"], as_dict=True).items():
            curve = curve.sort("wind_speed_mph")
            x, y = curve["wind_speed_mph"].to_numpy(), curve["building_loss_ratio"].to_numpy()
            if (len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all()
                    or np.any(np.diff(x) <= 0) or np.any((y < 0) | (y > 1))):
                raise ValueError("invalid event fragility curve")
            curve_lookup[key] = (x, y)

    rows = []
    for source in inputs.iter_rows(named=True):
        row = dict(source)
        affected = settings.states is None or row["state_code"] in settings.states
        gusts = [row[f"climate_scaled_rp_{period}_3sec_gust"] for period in periods]
        physical_issue = None
        gust = damage = None
        clamped = False
        for value in gusts:
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError("event gusts must be finite and positive")
        cost = row["active_installed_capex_usd"]
        if cost is not None and (not np.isfinite(cost) or cost < 0):
            raise ValueError("event installed costs must be finite and nonnegative")
        if all(value is not None for value in gusts):
            if settings.return_period == 300:
                if gusts[1] < gusts[0]:
                    raise ValueError("500-year gust must not be below 200-year gust")
                gust = gusts[0] + np.log(300 / 200) / np.log(500 / 200) * (gusts[1] - gusts[0])
                key = (row["asset_id"], row["scenario_id"])
                if key not in curve_lookup:
                    raise ValueError(f"missing verified effective curve for {key}")
                x, y = curve_lookup[key]
                damage = float(np.interp(gust, x, y))
                clamped = bool(gust < x[0] or gust > x[-1])
            else:
                gust = gusts[0]
                damage = row[f"rp_{settings.return_period}_damage_ratio"]
        if damage is not None and (not np.isfinite(damage) or not 0 <= damage <= 1):
            raise ValueError("event damage ratios must be finite and between 0 and 1")
        if affected:
            if gust is None or damage is None:
                physical_issue = "Event wind or damage ratio unavailable"
            elif cost is None:
                physical_issue = "Full installed roof cost unavailable"
        gross = damage * cost if affected and damage is not None and cost is not None else (None if affected else 0.0)
        payout_issue = physical_issue or (_policy_issue(row) if affected else None)
        payout = (
            min(max(gross - row["deductible_amount"], 0), row["insured_value"])
            if affected and payout_issue is None else (None if affected else 0.0)
        )
        row.update(
            affected=affected, local_gust_mph=gust,
            event_damage_ratio=damage if affected else 0.0,
            gross_event_damage_usd=gross, insured_event_payout_usd=payout,
            physical_issue=physical_issue, payout_issue=payout_issue,
            return_period=settings.return_period,
            gust_estimated=settings.return_period == 300,
            event_curve_clamped=clamped if settings.return_period == 300 else None,
        )
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(
        *(pl.col(column).cast(pl.Float64) for column in (*EVENT_METRICS, "event_damage_ratio", "local_gust_mph")),
        pl.col("physical_issue").cast(pl.String), pl.col("payout_issue").cast(pl.String),
    ).sort("asset_id", "scenario_id")


def _policy_issue(row: dict) -> Optional[str]:
    for field in ("insured_value", "deductible_amount"):
        value = row[field]
        if value is None or not np.isfinite(value):
            return f"Missing or invalid {field}"
    if row["insured_value"] <= 0 or row["deductible_amount"] < 0:
        return "Insured value must be positive and deductible nonnegative"
    if not row["policy_id"]:
        return "Missing policy_id"
    if row["deductible_type"] != "standard":
        return "Unsupported deductible type (Standard only)"
    if row["peril"] != "wind":
        return "Unmodeled peril (wind only)"
    return None


def summarize_event(rows: pl.DataFrame, *, by_state: bool = False) -> pl.DataFrame:
    """Never present an incomplete sum as a complete portfolio/state loss."""
    keys = ["scenario_id"]
    if by_state:
        keys.append("state_code")
        rows = rows.with_columns(pl.col("state_code").fill_null("Unknown"))
    return rows.group_by(keys).agg(
        pl.len().alias("asset_count"),
        pl.col("affected").sum().alias("affected_count"),
        *(
            expression
            for metric in EVENT_METRICS
            for expression in (
                pl.when(pl.col(metric).is_not_null().all())
                .then(pl.col(metric).sum()).otherwise(None).alias(metric),
                pl.col(metric).null_count().alias(f"{metric}_missing_count"),
            )
        ),
    ).sort(keys)
