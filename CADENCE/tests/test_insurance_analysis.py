import polars as pl
import pytest

from cadence.insurance.analysis import SCENARIOS, calculate_insurance
from cadence.insurance.contracts import normalize_policies
from cadence.ui.paths import DEFAULT_WORKBOOK
from cadence.ui.workbooks import _read_source_sheet


def _annual(repair=900.0):
    return pl.DataFrame({
        "asset_id": ["A"] * 8,
        "year": [2026] * 4 + [2027] * 4,
        "scenario_id": sorted(SCENARIOS) * 2,
        "annual_repair_cost_usd": [repair] * 8,
    })


def _policies(**overrides):
    data = {"asset_id": ["A"], "insured_value": [300], "policy_id": ["P"],
            "deductible_amount": [100], "deductible_type": [" Standard "],
            "peril": [" WIND "], "current_premium": [200]}
    data.update({key: [value] for key, value in overrides.items()})
    return normalize_policies(pl.DataFrame(data))


def test_default_workbook_policy_terms_are_supported():
    policies = normalize_policies(_read_source_sheet(DEFAULT_WORKBOOK, "Sheet1"))
    assert policies.height == 6
    assert policies["policy_issue"].null_count() == 6
    assert set(policies["deductible_type"]) == {"standard"}
    assert set(policies["source_deductible_type"]) == {"standard"}


def test_payout_cap_is_after_deductible_and_cumulative_is_per_scenario():
    results = calculate_insurance(_annual(), _policies())
    baseline = results.filter(pl.col("scenario_id") == "BASELINE_CURRENT")
    assert baseline["expected_payout_usd"].to_list() == [300, 300]
    assert baseline["premium_usd"].to_list() == [200, 200]
    assert baseline["underwriting_margin_usd"].to_list() == [-100, -100]
    assert baseline["cumulative_margin_usd"].to_list() == [-100, -200]


def test_zero_premium_and_deductible_floor():
    result = calculate_insurance(_annual(50), _policies(current_premium=0))
    assert result["expected_payout_usd"].to_list() == [0] * 8
    assert result["loss_ratio"].null_count() == 8
    assert result["underwriting_margin_usd"].to_list() == [0] * 8


@pytest.mark.parametrize("override", [
    {"deductible_type": "percent"}, {"deductible_type": None},
    {"peril": "hail"}, {"peril": None},
    {"insured_value": None}, {"current_premium": -1},
])
def test_unavailable_policy_does_not_create_a_payout(override):
    result = calculate_insurance(_annual(), _policies(**override))
    assert result["insurance_issue"].null_count() == 0
    assert result["expected_payout_usd"].null_count() == 8


def test_missing_repair_keeps_all_cumulative_values_unavailable_after_gap():
    annual = _annual().with_columns(
        pl.when(pl.col("year") == 2026).then(None)
        .otherwise(pl.col("annual_repair_cost_usd")).alias("annual_repair_cost_usd")
    )
    result = calculate_insurance(annual, _policies())
    assert result["expected_payout_usd"].null_count() == 4
    assert result["cumulative_payout_usd"].null_count() == 8


def test_missing_insurance_columns_are_explicitly_unavailable():
    policies = normalize_policies(pl.DataFrame({"asset_id": ["A"]}))
    assert policies["policy_issue"][0] == "Missing or invalid insured_value"
    assert calculate_insurance(_annual(), policies)["insurance_issue"].null_count() == 0


def test_requires_exact_asset_and_scenario_grain():
    with pytest.raises(ValueError, match="asset IDs"):
        calculate_insurance(_annual(), _policies(asset_id="B"))
    with pytest.raises(ValueError, match="three alternatives"):
        calculate_insurance(_annual().filter(pl.col("scenario_id") != "NEW_TILE"), _policies())