import pandas as pd

from cadence.economics.market_study import MATERIALS, simulate_asset


def inputs(start=2026, end=2028):
    prices = {
        (year, material): {
            "installed_usd": 100.0 if material == "OFFICIAL_ASPHALT" else 120.0,
            "material_usd": 60.0 if material == "OFFICIAL_ASPHALT" else 72.0,
            "labor_usd": 40.0 if material == "OFFICIAL_ASPHALT" else 48.0,
        }
        for year in range(start, end + 1) for material in MATERIALS
    }
    removal = {(year, material): {"disposal_usd": 2.0, "carbon_usd": 1.0}
               for year in range(start, end + 1) for material in MATERIALS}
    return prices, removal


def simulate(age, eul, prices, removal, risk, end=2028):
    return simulate_asset("A", "OFFICIAL_ASPHALT", age, eul,
                          {material: 2 for material in MATERIALS}, 2026, end,
                          0.02, prices, removal, risk)


def test_eul_replaces_at_start_and_costs_once() -> None:
    prices, removal = inputs()
    rows, decisions = simulate(2, 2, prices, removal, lambda year, material, age: (1.0, 0.0))
    assert rows["replacement_event"].tolist() == [True, False, True]
    assert rows["material_id"].tolist() == ["OFFICIAL_ASPHALT"] * 3
    assert rows["material_usd"].tolist() == [60.0, 0.0, 60.0]
    assert rows["disposal_usd"].tolist() == [2.0, 0.0, 2.0]
    assert rows.iloc[-1]["terminal_value_usd"] == 50.0
    assert decisions.groupby("year").size().to_dict() == {2026: 3, 2028: 3}
    assert set(decisions["cause"]) == {"EUL"}


def test_damage_plus_old_removal_triggers_before_eul() -> None:
    prices, removal = inputs(end=2026)
    rows, decisions = simulate(1, 2, prices, removal,
                               lambda year, material, age: (48.0 if age else 2.0, 0.0), end=2026)
    assert rows.iloc[0]["replacement_cause"] == "damage"
    assert decisions.iloc[0]["trigger_usd"] == 51.0
    assert decisions.iloc[0]["roof_value_usd"] == 50.0
    assert rows.iloc[0]["repair_usd"] == 2.0


def test_future_costs_change_winner_and_audit_incremental_npv() -> None:
    prices, removal = inputs()
    for year in range(2026, 2029):
        prices[year, "OFFICIAL_METAL"] = {"installed_usd": 125.0, "material_usd": 75.0, "labor_usd": 50.0}
    rows, decisions = simulate(2, 2, prices, removal,
                               lambda year, material, age: (40.0 if material != "OFFICIAL_METAL" else 1.0, 0.0))
    assert rows.iloc[0]["material_id"] == "OFFICIAL_METAL"
    chosen = decisions.loc[(decisions["year"] == 2026) & decisions["selected"]].iloc[0]
    assert chosen["candidate_material_id"] == "OFFICIAL_METAL"
    assert chosen["incremental_npv_usd"] > 0
    assert decisions.loc[(decisions["year"] == 2026) &
                         (decisions["candidate_material_id"] == "OFFICIAL_ASPHALT"), "incremental_npv_usd"].iloc[0] == 0


def test_missing_future_input_becomes_unknown_without_partial_costs() -> None:
    prices, removal = inputs()
    del prices[2028, "OFFICIAL_TILE"]
    rows, decisions = simulate(2, 2, prices, removal, lambda year, material, age: (1.0, 0.0))
    assert rows["material_id"].tolist() == ["UNKNOWN"] * 3
    assert rows["repair_usd"].isna().all()
    assert rows["unresolved_reason"].notna().all()
    assert decisions.empty