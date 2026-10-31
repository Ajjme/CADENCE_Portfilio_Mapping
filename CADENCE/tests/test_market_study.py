import pandas as pd
import numpy as np
import pytest

from cadence.economics.market_study import MATERIALS, AssetStudyInput, simulate_asset, simulate_assets


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
    assert decisions.groupby("year").size().to_dict() == {2026: 3, 2027: 3, 2028: 3}
    assert set(decisions["cause"]) == {"EUL", "none"}


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
    assert set(decisions["decision_reason"]) == {"unavailable"}
    assert not decisions["selected"].any()
    assert decisions["incremental_npv_usd"].isna().all()


def payback_inputs(end=2026):
    prices, removal = inputs(end=end)
    extra = sum(100 / 1.02 ** t for t in range(1, 11))
    for (year, material) in prices:
        cost = 10000 + (extra if material == "OFFICIAL_METAL" else 20000 if material == "OFFICIAL_TILE" else 0)
        prices[year, material] = {"installed_usd": cost, "material_usd": cost * 0.6, "labor_usd": cost * 0.4}
        removal[year, material] = {"disposal_usd": 0.0, "carbon_usd": 0.0}
    return prices, removal, extra


def payback_run(limit=None, age=20, end=2026, risk=None, sink=None):
    prices, removal, _ = payback_inputs(end)
    return simulate_asset(
        "A", "OFFICIAL_ASPHALT", age, 20, dict.fromkeys(MATERIALS, 20),
        2026, end, 0.02, prices, removal,
        risk or (lambda year, material, age: (0.0 if material == "OFFICIAL_METAL" else 100.0, 0.0)),
        limit, sink,
    )


def test_exact_discounted_payback_cutoff_and_required_fallback():
    rows10, d10 = payback_run(10)
    rows9, d9 = payback_run(9)
    metal10 = d10.loc[d10.candidate_material_id == "OFFICIAL_METAL"].iloc[0]
    metal9 = d9.loc[d9.candidate_material_id == "OFFICIAL_METAL"].iloc[0]
    assert metal10.discounted_payback_years == 10
    assert metal10.savings_at_limit_usd == pytest.approx(0, abs=1e-9)
    assert metal10.incremental_npv_usd > 0
    assert metal10.selected
    assert not metal9.selected
    assert metal9.decision_reason == "payback_exceeds_limit"
    assert rows10.iloc[0].material_id == "OFFICIAL_METAL"
    assert rows9.iloc[0].material_id == "OFFICIAL_ASPHALT"
    assert rows9.iloc[0].replacement_event
    assert d9.loc[d9.selected, "decision_reason"].item() == "required_in_kind"


def test_recovery_after_ten_is_rejected_until_limit_is_long_enough():
    prices, removal, _ = payback_inputs()
    extra = sum(100 / 1.02 ** t for t in range(1, 13))
    prices[2026, "OFFICIAL_METAL"] = {
        "installed_usd": 10000 + extra, "material_usd": 10000 + extra, "labor_usd": 0.0,
    }
    for limit, accepted in ((10, False), (12, True)):
        _, decisions = simulate_asset(
            "A", "OFFICIAL_ASPHALT", 20, 20, dict.fromkeys(MATERIALS, 20),
            2026, 2026, 0.02, prices, removal,
            lambda year, material, age: (0.0 if material == "OFFICIAL_METAL" else 100.0, 0.0), limit,
        )
        metal = decisions.loc[decisions.candidate_material_id == "OFFICIAL_METAL"].iloc[0]
        assert metal.incremental_npv_usd > 0
        assert metal.discounted_payback_years == 12
        assert metal.selected == accepted


def test_positive_npv_and_short_payback_are_separate_gates():
    def risk(year, material, age):
        if material == "OFFICIAL_METAL":
            return (20000.0 if year >= 2037 else 0.0), 0.0
        return 100.0, 0.0
    # Supply observed future years so the post-payback cost increase is not frozen away.
    _, decisions = payback_run(10, end=2046, risk=risk)
    metal = decisions.loc[(decisions.year == 2026) & (decisions.candidate_material_id == "OFFICIAL_METAL")].iloc[0]
    assert metal.discounted_payback_years == 10
    assert metal.incremental_npv_usd < 0
    assert not metal.eligible


def test_elective_replacement_is_checked_annually_and_limit_can_defer():
    prices, removal = inputs(end=2028)
    for key in prices:
        material = key[1]
        cost = 100 if material != "OFFICIAL_TILE" else 1000
        prices[key] = {"installed_usd": cost, "material_usd": cost, "labor_usd": 0.0}
        removal[key] = {"disposal_usd": 0.0, "carbon_usd": 0.0}
    risk = lambda year, material, age: (0.0 if material == "OFFICIAL_METAL" else 6.0, 0.0)
    args = ("A", "OFFICIAL_ASPHALT", 0, 20, dict.fromkeys(MATERIALS, 20),
            2026, 2028, 0.0, prices, removal, risk)
    unlimited, decisions = simulate_asset(*args)
    limited, _ = simulate_asset(*args, max_payback_years=1)
    assert unlimited.iloc[0].replacement_cause == "economic"
    assert unlimited.iloc[0].material_id == "OFFICIAL_METAL"
    assert not limited.replacement_event.any()
    assert decisions.loc[decisions.year == 2026, "incremental_upfront_usd"].min() == 100


def test_payback_limit_defers_upgrade_until_a_later_year():
    prices, removal = inputs()
    for year, material in prices:
        cost = 1000.0 if material == "OFFICIAL_TILE" else 100.0
        if material == "OFFICIAL_METAL":
            cost = 120.0 if year == 2026 else 10.0
        prices[year, material] = {"installed_usd": cost, "material_usd": cost, "labor_usd": 0.0}
        removal[year, material] = {"disposal_usd": 0.0, "carbon_usd": 0.0}
    rows, decisions = simulate_asset(
        "A", "OFFICIAL_ASPHALT", 0, 20, dict.fromkeys(MATERIALS, 20),
        2026, 2028, 0, prices, removal,
        lambda year, material, age: (0.0 if material == "OFFICIAL_METAL" else 6.0, 0.0), 3,
    )
    assert rows.replacement_event.tolist() == [False, True, False]
    assert rows.iloc[1].replacement_cause == "economic"
    assert decisions.loc[(decisions.year == 2026) & (decisions.candidate_material_id == "OFFICIAL_METAL"),
                         "incremental_npv_usd"].item() == pytest.approx(5)
    assert decisions.loc[(decisions.year == 2026) & (decisions.candidate_material_id == "OFFICIAL_METAL"),
                         "decision_reason"].item() == "payback_exceeds_limit"


def test_cash_flow_audit_reconciles_npv_and_excludes_terminal_from_payback():
    ledgers = []
    _, decisions = payback_run(10, sink=ledgers.append)
    audit = pd.concat(ledgers)
    for row in decisions.itertuples():
        flows = audit.loc[audit.candidate_material_id == row.candidate_material_id]
        opening = sum(
            (flows[f"baseline_{c}"] - flows[f"candidate_{c}"])
            for c in ("material_usd", "labor_usd", "disposal_usd", "carbon_usd")
        )
        closing = sum(
            (flows[f"baseline_{c}"] - flows[f"candidate_{c}"]) for c in ("repair_usd", "loss_of_use_usd")
        )
        pv = (opening * flows.opening_discount_factor + closing * flows.closing_discount_factor).sum()
        assert row.incremental_npv_usd == pytest.approx(pv + row.terminal_value_contribution_usd)
        assert flows.iloc[-1].cumulative_discounted_savings_usd == pytest.approx(pv)
    assert audit.cash_flow_year.max() == 2045
    assert audit.extrapolated_inputs.any()


def test_extension_holds_source_year_not_roof_age_and_large_limit_is_not_clipped():
    calls = []
    def risk(year, material, age):
        calls.append((year, age))
        return age * 0.01, 0.0
    _, decisions = payback_run(35, risk=risk)
    assert set(decisions.evaluation_years) == {35}
    assert set(decisions.max_payback_years) == {35}
    assert {year for year, _ in calls} == {2026}
    assert len({age for _, age in calls}) > 10


def test_terminal_value_can_make_npv_positive_but_cannot_pay_back():
    prices, removal = inputs(end=2026)
    for material, cost in zip(MATERIALS, (100.0, 120.0, 100000.0)):
        prices[2026, material] = {"installed_usd": cost, "material_usd": cost, "labor_usd": 0.0}
        removal[2026, material] = {"disposal_usd": 0.0, "carbon_usd": 0.0}
    _, decisions = simulate_asset(
        "A", "OFFICIAL_ASPHALT", 20, 20, dict(zip(MATERIALS, (20, 25, 40))),
        2026, 2026, 0, prices, removal, lambda *_: (0, 0), 10,
    )
    metal = decisions.loc[decisions.candidate_material_id == "OFFICIAL_METAL"].iloc[0]
    assert metal.incremental_npv_usd == pytest.approx(8)
    assert metal.terminal_value_contribution_usd == pytest.approx(48)
    assert metal.savings_at_limit_usd == -20
    assert metal.discounted_payback_years == 20
    assert not metal.selected


@pytest.mark.parametrize("limit", [0, -1, 1.5, float("inf"), float("nan"), True, "10"])
def test_invalid_payback_limits_raise(limit):
    with pytest.raises(ValueError, match="positive whole"):
        payback_run(limit)


def test_immediate_recovery_zero_discount_and_deterministic_ties():
    prices, removal = inputs(end=2026)
    for material in MATERIALS:
        prices[2026, material] = {"installed_usd": 100.0, "material_usd": 100.0, "labor_usd": 0.0}
    rows, decisions = simulate_asset("A", "OFFICIAL_METAL", 2, 2, dict.fromkeys(MATERIALS, 2),
                                     2026, 2026, 0.0, prices, removal, lambda *_: (0.0, 0.0), 1)
    assert rows.iloc[0].material_id == "OFFICIAL_METAL"
    assert (decisions.discounted_payback_years == 0).all()
    assert not decisions.npv_eligible.any()
    assert decisions.selected.sum() == 1


def test_batched_different_horizons_match_single_home_results():
    prices, removal, _ = payback_inputs()
    risk = lambda year, material, age: (0.0 if material == "OFFICIAL_METAL" else age * 2.0, 0.0)
    assets = [
        AssetStudyInput(str(i), "OFFICIAL_ASPHALT", i, 20 + i, dict.fromkeys(MATERIALS, 20 + i),
                        prices, removal, risk) for i in range(3)
    ]
    annual, decisions = simulate_assets(assets, 2026, 2026, 0.02, 10)
    for asset in assets:
        one, audit = simulate_assets([asset], 2026, 2026, 0.02, 10)
        pd.testing.assert_frame_equal(annual.loc[annual.asset_id == asset.asset_id].reset_index(drop=True), one)
        pd.testing.assert_frame_equal(decisions.loc[decisions.asset_id == asset.asset_id].reset_index(drop=True), audit)


def test_missing_risk_only_marks_affected_home_unknown():
    prices, removal, _ = payback_inputs()
    assets = [
        AssetStudyInput("good", "OFFICIAL_ASPHALT", 20, 20, dict.fromkeys(MATERIALS, 20),
                        prices, removal, lambda *_: (0.0, 0.0)),
        AssetStudyInput("bad", "OFFICIAL_ASPHALT", 20, 20, dict.fromkeys(MATERIALS, 20),
                        prices, removal, lambda *_: (np.nan, 0.0)),
    ]
    annual, decisions = simulate_assets(assets, 2026, 2026, 0.02)
    assert annual.set_index("asset_id").loc["good", "material_id"] != "UNKNOWN"
    assert annual.set_index("asset_id").loc["bad", "material_id"] == "UNKNOWN"
    assert not decisions.loc[decisions.asset_id == "bad", "selected"].any()