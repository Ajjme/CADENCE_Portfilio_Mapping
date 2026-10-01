"""Finite-horizon, event-driven roof replacement decisions."""

from __future__ import annotations

from functools import lru_cache
from math import isfinite
from typing import Callable

import pandas as pd

MATERIALS = ("OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE")
COMPONENTS = ("repair_usd", "loss_of_use_usd", "material_usd", "labor_usd", "disposal_usd", "carbon_usd")


def simulate_asset(
    asset_id: str,
    current_material: str,
    roof_age: int,
    current_eul: int,
    service_lives: dict[str, int],
    start_year: int,
    end_year: int,
    discount_rate: float,
    option_costs: dict[tuple[int, str], dict[str, float]],
    removal_costs: dict[tuple[int, str], dict[str, float]],
    annual_risk: Callable[[int, str, int], tuple[float, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Optimize replacement at each event, returning paid costs and decision audit."""
    if current_material not in MATERIALS or roof_age < 0 or current_eul <= 0:
        raise ValueError("invalid initial roof state")
    if start_year > end_year or discount_rate < 0 or any(service_lives.get(m, 0) <= 0 for m in MATERIALS):
        raise ValueError("invalid study horizon, rate, or service lives")

    def option(year: int, material: str) -> dict[str, float]:
        costs = option_costs[(year, material)]
        if not all(isfinite(float(costs[name])) and costs[name] >= 0 for name in ("installed_usd", "material_usd", "labor_usd")):
            raise ValueError("unavailable installation costs")
        return costs

    def removal(year: int, material: str) -> dict[str, float]:
        costs = removal_costs[(year, material)]
        if not all(isfinite(float(costs[name])) and costs[name] >= 0 for name in ("disposal_usd", "carbon_usd")):
            raise ValueError("unavailable removal costs")
        return costs

    def risk(year: int, material: str, age: int) -> tuple[float, float]:
        repair, loss = annual_risk(year, material, age)
        if not all(isfinite(float(value)) and value >= 0 for value in (repair, loss)):
            raise ValueError("unavailable annual risk")
        return repair, loss

    def trigger(year: int, material: str, age: int, eul: int) -> tuple[bool, str, float, float]:
        installed = option(year, material)["installed_usd"]
        removal_cost = removal(year, material)
        repair, loss = risk(year, material, age)
        threshold = installed * max(0.0, 1.0 - age / eul)
        exposure = repair + loss + removal_cost["disposal_usd"] + removal_cost["carbon_usd"]
        cause = "EUL" if age >= eul else "damage" if exposure > threshold else "none"
        return cause != "none", cause, exposure, threshold

    @lru_cache(maxsize=None)
    def candidate_cost(year: int, incoming: str, replacement: str) -> float:
        old = removal(year, incoming)
        installed = option(year, replacement)["installed_usd"]
        repair, loss = risk(year, replacement, 0)
        future, _ = optimal(year + 1, replacement, 1, service_lives[replacement])
        return installed + old["disposal_usd"] + old["carbon_usd"] + repair + loss + future / (1.0 + discount_rate)

    @lru_cache(maxsize=None)
    def optimal(year: int, material: str, age: int, eul: int) -> tuple[float, str | None]:
        if year > end_year:
            return (-option(end_year, material)["installed_usd"] * max(0.0, 1.0 - age / eul), None)
        due, _, _, _ = trigger(year, material, age, eul)
        if not due:
            repair, loss = risk(year, material, age)
            future, _ = optimal(year + 1, material, age + 1, eul)
            return (repair + loss + future / (1.0 + discount_rate), None)
        return min((candidate_cost(year, material, replacement), replacement) for replacement in MATERIALS)

    rows: list[dict] = []
    decisions: list[dict] = []
    material, age, eul = current_material, roof_age, current_eul
    unresolved = False
    for year in range(start_year, end_year + 1):
        if unresolved:
            rows.append({"asset_id": asset_id, "year": year, "material_id": "UNKNOWN", "replacement_event": False,
                         "terminal_value_usd": None, "unresolved_reason": unresolved_reason,
                         **{name: None for name in COMPONENTS}})
            continue
        try:
            due, cause, exposure, threshold = trigger(year, material, age, eul)
            incoming = material
            replacement = None
            if due:
                _, replacement = optimal(year, material, age, eul)
                old = removal(year, material)
                reference = candidate_cost(year, incoming, incoming)
                for candidate in MATERIALS:
                    decisions.append({"asset_id": asset_id, "year": year, "cause": cause,
                                      "old_material_id": incoming, "candidate_material_id": candidate,
                                      "selected": candidate == replacement,
                                      "trigger_usd": exposure, "roof_value_usd": threshold,
                                      "incremental_npv_usd": reference - candidate_cost(year, incoming, candidate)})
                material = str(replacement)
                age, eul = 0, service_lives[material]
                installed = option(year, material)
            else:
                old = {"disposal_usd": 0.0, "carbon_usd": 0.0}
                installed = {"material_usd": 0.0, "labor_usd": 0.0}
            repair, loss = risk(year, material, age)
            rows.append({"asset_id": asset_id, "year": year, "material_id": material, "opening_material_id": incoming,
                         "age_years": age, "replacement_event": due, "replacement_cause": cause,
                         "repair_usd": repair, "loss_of_use_usd": loss,
                         "material_usd": installed["material_usd"], "labor_usd": installed["labor_usd"],
                         "disposal_usd": old["disposal_usd"], "carbon_usd": old["carbon_usd"],
                         "terminal_value_usd": (option(year, material)["installed_usd"] * max(0.0, 1.0 - (age + 1) / eul)
                                                if year == end_year else 0.0), "unresolved_reason": None})
            age += 1
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
            unresolved = True
            unresolved_reason = str(error)
            rows.append({"asset_id": asset_id, "year": year, "material_id": "UNKNOWN", "replacement_event": False,
                         "terminal_value_usd": None, "unresolved_reason": unresolved_reason,
                         **{name: None for name in COMPONENTS}})
    return pd.DataFrame(rows), pd.DataFrame(decisions)