"""Annual keep-versus-replace decisions with a discounted-payback gate."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from typing import Callable

import numpy as np
import pandas as pd

MATERIALS = ("OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE")
COMPONENTS = ("repair_usd", "loss_of_use_usd", "material_usd", "labor_usd", "disposal_usd", "carbon_usd")
POLICY_ID = "annual_fixed_path_npv_discounted_payback_v2"
EXTENSION_POLICY = "hold_last_saved_real_prices_and_climate_age_risk_v1"
TIMING_POLICY = "opening_installation_closing_operations_terminal_at_L_v1"


def validate_payback_limit(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("Maximum acceptable payback must be a positive whole number of years")
    return value


@dataclass
class AssetStudyInput:
    asset_id: str
    current_material: str
    roof_age: int
    current_eul: int
    service_lives: dict[str, int]
    option_costs: dict[tuple[int, str], dict[str, float]]
    removal_costs: dict[tuple[int, str], dict[str, float]]
    annual_risk: Callable[[int, str, int], tuple[float, float]]


def simulate_assets(
    assets: list[AssetStudyInput],
    start_year: int,
    end_year: int,
    discount_rate: float,
    max_payback_years: int | None = None,
    audit_sink: Callable[[pd.DataFrame], None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate four fixed paths in bounded asset batches; never recursively optimize."""
    limit = validate_payback_limit(max_payback_years)
    if not assets or start_year > end_year or not isfinite(discount_rate) or discount_rate < 0:
        raise ValueError("invalid study assets, horizon, or discount rate")
    for asset in assets:
        if (asset.current_material not in MATERIALS or asset.roof_age < 0 or asset.current_eul <= 0
                or any(asset.service_lives.get(m, 0) <= 0 for m in MATERIALS)):
            raise ValueError(f"invalid initial roof state or service lives: {asset.asset_id}")
    if len({asset.asset_id for asset in assets}) != len(assets):
        raise ValueError("duplicate study asset IDs")
    n, years = len(assets), end_year - start_year + 1
    idx = np.arange(n)
    ids = np.array([a.asset_id for a in assets])
    materials = np.array(MATERIALS)
    current = np.array([MATERIALS.index(a.current_material) for a in assets])
    age = np.array([a.roof_age for a in assets])
    eul = np.array([a.current_eul for a in assets])
    lives = np.array([[a.service_lives[m] for m in MATERIALS] for a in assets])
    duration = np.maximum(np.maximum(lives.max(axis=1), eul), limit or 0)
    length = int(duration.max())
    discounts = np.exp(-np.log1p(discount_rate) * np.arange(length + 1))
    prices = np.full((n, years, 3, 4), np.nan)
    errors: dict[int, str] = {}
    for i, asset in enumerate(assets):
        try:
            for y in range(years):
                for m, material in enumerate(MATERIALS):
                    option = asset.option_costs[start_year + y, material]
                    removal = asset.removal_costs[start_year + y, material]
                    values = [option["material_usd"], option["labor_usd"],
                              removal["disposal_usd"], removal["carbon_usd"]]
                    if (not all(isfinite(v) and v >= 0 for v in values)
                            or not isfinite(option["installed_usd"])
                            or abs(sum(values[:2]) - option["installed_usd"]) > 0.005):
                        raise ValueError("unavailable or inconsistent installation/removal costs")
                    prices[i, y, m] = values
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            errors[i] = f"{asset.asset_id}: {error}"

    @lru_cache(maxsize=250000)
    def risk(i: int, year: int, material: int, roof_age: int) -> tuple[float, float]:
        try:
            values = assets[i].annual_risk(min(year, end_year), MATERIALS[material], roof_age)
            if len(values) != 2 or not all(isfinite(v) and v >= 0 for v in values):
                raise ValueError("unavailable annual risk")
            return values
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
            errors[i] = f"{assets[i].asset_id}: {error}"
            return float("nan"), float("nan")

    def risk_array(year: int, mat: np.ndarray, ages: np.ndarray, active: np.ndarray) -> np.ndarray:
        values = np.zeros((*mat.shape, 2))
        for i, p in zip(*np.nonzero(active)):
            if i in errors:
                values[i, p] = np.nan
            else:
                values[i, p] = risk(int(i), year, int(mat[i, p]), int(ages[i, p]))
        return values

    annual_frames = []
    decision_frames = []
    for year in range(start_year, end_year + 1):
        # Column zero keeps the roof; columns 1..3 install each material now.
        mat = np.column_stack((current, np.broadcast_to(np.arange(3), (n, 3))))
        ages = np.broadcast_to(age[:, None], (n, 4)).copy()
        euls = np.broadcast_to(eul[:, None], (n, 4)).copy()
        cash = np.zeros((n, 4, length, len(COMPONENTS)))
        path_ages = np.zeros((n, 4, length), dtype=int)
        path_events = np.zeros((n, 4, length), dtype=bool)
        terminal = np.zeros((n, 4))
        first_cause = np.full(n, "none", dtype=object)
        exposure = np.zeros(n)
        roof_value = np.zeros(n)
        for t in range(length):
            active = np.broadcast_to((t < duration)[:, None], (n, 4))
            yi = min(year + t, end_year) - start_year
            incoming = np.broadcast_to(current[:, None], (n, 4)) if t == 0 else mat
            cost = prices[idx[:, None], yi, incoming]
            operating = risk_array(year + t, incoming, ages, active)
            value = cost[:, :, :2].sum(axis=2) * np.maximum(0, 1 - ages / euls)
            exposed = operating.sum(axis=2) + cost[:, :, 2:].sum(axis=2)
            due = ((ages >= euls) | (exposed > value)) & active
            if t == 0:
                first_cause = np.where(ages[:, 0] >= euls[:, 0], "EUL",
                                       np.where(due[:, 0], "damage", "none"))
                exposure, roof_value = exposed[:, 0], value[:, 0]
                due[:, 1:] = True
            ages = np.where(due, 0, ages)
            euls = np.where(due, lives[idx[:, None], mat], euls)
            installed = prices[idx[:, None], yi, mat]
            cash[:, :, t, :2] = risk_array(year + t, mat, ages, active)
            cash[:, :, t, 2:4] = np.where(due[:, :, None], installed[:, :, :2], 0)
            cash[:, :, t, 4:] = np.where(due[:, :, None], cost[:, :, 2:], 0)
            path_ages[:, :, t], path_events[:, :, t] = ages, due
            ages = ages + active
            terminal_year = min(year + t + 1, end_year) - start_year
            value_at_end = prices[idx[:, None], terminal_year, mat, :2].sum(axis=2)
            terminal = np.where((t + 1 == duration)[:, None],
                                value_at_end * np.maximum(0, 1 - ages / euls), terminal)

        diff = cash[:, :1] - cash[:, 1:]
        opening = diff[:, :, :, 2:].sum(axis=3)
        closing = diff[:, :, :, :2].sum(axis=3)
        boundary = np.zeros((n, 3, length + 1))
        boundary[:, :, :-1] += opening * discounts[:-1]
        boundary[:, :, 1:] += closing * discounts[1:]
        cumulative = boundary.cumsum(axis=2)
        terminal_delta = (terminal[:, 1:] - terminal[:, :1]) * discounts[duration, None]
        npv = cumulative[:, :, -1] + terminal_delta
        finite = (np.isfinite(cash).all(axis=(1, 2, 3))
                  & np.isfinite(cumulative).all(axis=(1, 2)) & np.isfinite(npv).all(axis=1))
        for i in np.flatnonzero(~finite):
            errors.setdefault(int(i), f"{ids[i]}: nonfinite candidate cash flows or NPV")
        recovered = (np.round(cumulative, 2) >= 0) & (np.arange(length + 1) <= duration[:, None, None])
        payback = np.where(recovered.any(axis=2), recovered.argmax(axis=2), np.nan)
        npv_ok = np.round(npv, 2) > 0
        payback_ok = np.ones((n, 3), dtype=bool) if limit is None else payback <= limit
        eligible = npv_ok & payback_ok
        valid = np.array([i not in errors for i in idx])
        eligible &= valid[:, None]
        ranked = np.where(eligible, np.round(npv, 2), -np.inf)
        best = ranked.argmax(axis=1)
        # Same-material ties precede canonical material order.
        same_tie = eligible[idx, current] & (ranked[idx, current] == ranked[idx, best])
        best = np.where(same_tie, current, best)
        mandatory = first_cause != "none"
        chosen = np.where(eligible.any(axis=1), best, np.where(mandatory, current, -1))
        chosen = np.where(valid, chosen, -1)
        selected_path = chosen + 1
        selected_path = np.where(chosen < 0, 0, selected_path)
        paid = cash[idx, selected_path, 0].copy()
        paid[~valid] = np.nan
        actual_mat = np.where(chosen >= 0, chosen, current)
        actual_age = path_ages[idx, selected_path, 0]
        reason = np.where(~valid, "unavailable",
                          np.where(chosen >= 0, np.where(mandatory, first_cause, "economic"), "none"))
        annual = pd.DataFrame({
            "asset_id": ids, "year": year,
            "opening_material_id": materials[current],
            "material_id": np.where(valid, materials[actual_mat], "UNKNOWN"),
            "age_years": actual_age, "replacement_event": valid & (chosen >= 0),
            "replacement_cause": reason,
            "unresolved_reason": [errors.get(i) for i in idx],
            **{name: paid[:, c] for c, name in enumerate(COMPONENTS)},
        })
        actual_eul = np.where(chosen >= 0, lives[idx, actual_mat], eul)
        value = prices[idx, min(year + 1, end_year) - start_year, actual_mat, :2].sum(axis=1)
        annual["terminal_value_usd"] = np.where(
            valid, value * np.maximum(0, 1 - (actual_age + 1) / actual_eul) if year == end_year else 0, np.nan,
        )
        annual_frames.append(annual)
        selected = (chosen[:, None] == np.arange(3)) & valid[:, None]
        rejection = np.where(~npv_ok, "nonpositive_npv",
                             np.where(~payback_ok, "payback_exceeds_limit", "lower_ranked"))
        rejection = np.where(selected, np.where(eligible, "accepted", "required_in_kind"), rejection)
        rejection = np.where(~valid[:, None], "unavailable", rejection)
        for array in (npv, payback, terminal_delta):
            array[~valid] = np.nan
        decision = pd.DataFrame({
            "asset_id": np.repeat(ids, 3), "year": year,
            "old_material_id": np.repeat(materials[current], 3),
            "candidate_material_id": np.tile(materials, n),
            "cause": np.repeat(first_cause, 3), "required_replacement": np.repeat(mandatory, 3),
            "comparison": "keep_until_required_then_in_kind",
            "evaluation_years": np.repeat(duration, 3),
            "max_payback_years": limit,
            "trigger_usd": np.repeat(exposure, 3), "roof_value_usd": np.repeat(roof_value, 3),
            "incremental_upfront_usd": -opening[:, :, 0].ravel(),
            "incremental_npv_usd": npv.ravel(),
            "terminal_value_contribution_usd": terminal_delta.ravel(),
            "baseline_terminal_value_usd": np.repeat(terminal[:, 0], 3),
            "candidate_terminal_value_usd": terminal[:, 1:].ravel(),
            "discounted_payback_years": payback.ravel(),
            "payback_status": np.where(np.isfinite(payback), "recovered",
                                       "not_recovered_within_evaluated_horizon").ravel(),
            "savings_at_limit_usd": cumulative[:, :, limit].ravel() if limit else np.nan,
            "npv_eligible": (npv_ok & valid[:, None]).ravel(),
            "payback_eligible": (payback_ok & valid[:, None]).ravel(),
            "eligible": eligible.ravel(), "selected": selected.ravel(),
            "decision_reason": rejection.ravel(),
            "unresolved_reason": np.repeat([errors.get(i) for i in idx], 3),
            "extrapolated_inputs": np.repeat(year + duration > end_year, 3),
        })
        decision.loc[~np.repeat(valid, 3), "payback_status"] = "unavailable"
        decision.loc[~np.repeat(valid, 3), [
            "incremental_upfront_usd", "baseline_terminal_value_usd",
            "candidate_terminal_value_usd", "savings_at_limit_usd",
        ]] = np.nan
        decision_frames.append(decision)
        if audit_sink is not None:
            ai, ci, ti = np.nonzero(np.broadcast_to(
                (np.arange(length) < duration[:, None])[:, None, :], (n, 3, length),
            ))
            audit_sink(pd.DataFrame({
                "asset_id": ids[ai], "decision_year": year,
                "candidate_material_id": materials[ci],
                "cash_flow_year": year + ti, "elapsed_year": ti,
                "baseline_age_years": path_ages[ai, 0, ti],
                "candidate_age_years": path_ages[ai, ci + 1, ti],
                "baseline_replacement": path_events[ai, 0, ti],
                "candidate_replacement": path_events[ai, ci + 1, ti],
                "opening_discount_factor": discounts[ti],
                "closing_discount_factor": discounts[ti + 1],
                "cumulative_discounted_savings_usd": cumulative[ai, ci, ti + 1],
                "available": valid[ai],
                "extrapolated_inputs": year + ti > end_year,
                **{f"baseline_{name}": cash[ai, 0, ti, c] for c, name in enumerate(COMPONENTS)},
                **{f"candidate_{name}": cash[ai, ci + 1, ti, c] for c, name in enumerate(COMPONENTS)},
            }))
        current, age, eul = actual_mat, actual_age + 1, actual_eul
    return pd.concat(annual_frames, ignore_index=True), pd.concat(decision_frames, ignore_index=True)


def simulate_asset(
    asset_id: str, current_material: str, roof_age: int, current_eul: int,
    service_lives: dict[str, int], start_year: int, end_year: int, discount_rate: float,
    option_costs: dict[tuple[int, str], dict[str, float]],
    removal_costs: dict[tuple[int, str], dict[str, float]],
    annual_risk: Callable[[int, str, int], tuple[float, float]],
    max_payback_years: int | None = None,
    audit_sink: Callable[[pd.DataFrame], None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Single-home adapter for the batched annual decision engine."""
    return simulate_assets(
        [AssetStudyInput(asset_id, current_material, roof_age, current_eul, service_lives,
                         option_costs, removal_costs, annual_risk)],
        start_year, end_year, discount_rate, max_payback_years, audit_sink,
    )
