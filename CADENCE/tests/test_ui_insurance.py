from pathlib import Path

import pandas as pd
import polars as pl
from streamlit.testing.v1 import AppTest

from cadence.insurance.pipeline import publish_insurance
from cadence.ui import insurance_data
from cadence.ui.insurance_charts import coverage_figure
from cadence.ui.pages import insurance
from cadence.ui.results_data import PORTFOLIO_OPTION


def test_dashboard_registers_all_pages(monkeypatch):
    import streamlit as st

    from cadence.ui.pages import portfolio

    page_titles = []
    navigate = st.navigation

    def capture_navigation(pages):
        page_titles.extend(page.title for page in pages)
        return navigate(pages)

    monkeypatch.setattr(st, "navigation", capture_navigation)
    monkeypatch.setattr(portfolio, "render", lambda: st.write("Portfolio"))
    app_path = Path(insurance.__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run()

    assert not app.exception
    assert page_titles == [
        "Asset Portfolio", "Alternative Analysis Results", "Insurance View",
    ]


def _insurance_page():
    from cadence.ui.pages import insurance

    insurance.render()


def test_unavailable_page_explains_older_runs(monkeypatch):
    monkeypatch.setattr(insurance, "discover_insurance_runs", lambda: [])
    app = AppTest.from_function(_insurance_page).run()
    assert not app.exception
    assert "No insurance policy snapshot" in app.info[0].value


def test_portfolio_incomplete_results_do_not_silently_sum(tmp_path: Path, monkeypatch):
    root = tmp_path / "physical" / "schema_version=v0.4.0" / "run_id=physical"
    annual = root / "annual_alternative_analysis" / "year=2026"
    annual.mkdir(parents=True)
    pl.DataFrame({
        "asset_id": ["A"] * 4 + ["B"] * 4,
        "year": [2026] * 8,
        "scenario_id": ["BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE"] * 2,
        "annual_repair_cost_usd": [150.] * 8,
    }).write_parquet(annual / "part-00000.parquet")
    policies = pl.DataFrame({
        "asset_id": ["A", "B"], "policy_id": ["P", "Q"],
        "insured_value": [500, 500], "deductible_amount": [50, 50],
        "deductible_type": ["standard", "standard"], "peril": ["wind", "hail"],
        "current_premium": [200, 200],
    })
    monkeypatch.setattr(insurance_data, "INSURANCE_ROOT", tmp_path / "insurance")
    monkeypatch.setattr(insurance_data, "load_run_metadata", lambda _: {
        "run_id": "physical", "asset_count": 2,
    })
    run = publish_insurance(root, {"run_id": "physical", "schema_version": "v0.4.0"},
                            policies, "workbook", insurance_data.INSURANCE_ROOT)
    frame = insurance_data.load_insurance_series(run["run_root"], PORTFOLIO_OPTION)
    assert frame["missing_count"].eq(1).all()
    assert frame["expected_payout_usd"].isna().all()
    assert frame["premium_usd"].isna().all()
    assert insurance_data.load_insurance_series(run["run_root"], "A")["expected_payout_usd"].eq(100).all()


def test_portfolio_cumulative_totals_remain_missing_after_an_earlier_gap(tmp_path: Path, monkeypatch):
    root = tmp_path / "insurance" / "schema_version=v0.1.0" / "run_id=sample"
    for year, first_asset_cumulative in ((2026, None), (2027, None)):
        partition = root / "annual_insurance" / f"year={year}"
        partition.mkdir(parents=True)
        pl.DataFrame({
            "asset_id": ["A", "B"], "year": [year, year],
            "scenario_id": ["BASELINE_CURRENT"] * 2,
            "insurance_issue": ["Missing repair" if year == 2026 else None, None],
            "insured_value": [100., 100.],
            "premium_usd": [None if year == 2026 else 10., 10.],
            "expected_payout_usd": [None if year == 2026 else 2., 2.],
            "underwriting_margin_usd": [None if year == 2026 else 8., 8.],
            "cumulative_premium_usd": [first_asset_cumulative, 10. if year == 2026 else 20.],
            "cumulative_payout_usd": [first_asset_cumulative, 2. if year == 2026 else 4.],
            "cumulative_margin_usd": [first_asset_cumulative, 8. if year == 2026 else 16.],
        }).write_parquet(partition / "part-00000.parquet")
    monkeypatch.setattr(insurance_data, "load_insurance_metadata", lambda _: {"asset_count": 2})
    frame = insurance_data.load_insurance_series(str(root), PORTFOLIO_OPTION)
    later = frame.loc[frame["year"] == 2027].iloc[0]
    assert later["premium_usd"] == 20
    assert pd.isna(later["cumulative_premium_usd"])


def test_insurance_view_renders_asset_and_portfolio(monkeypatch):
    metadata = {"run_id": "insurance", "physical_run_id": "physical", "asset_count": 1,
                "year_start": 2026, "year_end": 2027, "schema_version": "v0.1.0"}
    policies = pd.DataFrame({"asset_id": ["A"], "policy_id": ["P"],
                             "insured_value": [500.], "deductible_amount": [50.],
                             "current_premium": [200.], "policy_issue": [None]})
    series = pd.DataFrame([
        {"asset_id": "A", "year": year, "scenario_id": scenario,
         "insured_value": 500., "premium_usd": 200., "expected_payout_usd": 100.,
         "annual_repair_cost_usd": 150., "deductible_amount": 50., "policy_id": "P",
         "underwriting_margin_usd": 100., "loss_ratio": .5,
         "cumulative_premium_usd": 200. * (year - 2025),
         "cumulative_payout_usd": 100. * (year - 2025),
         "cumulative_margin_usd": 100. * (year - 2025), "insurance_issue": None,
         "missing_count": 0}
        for year in (2026, 2027)
        for scenario in ("BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
    ])
    monkeypatch.setattr(insurance, "discover_insurance_runs", lambda: [{**metadata, "run_root": "/unused"}])
    monkeypatch.setattr(insurance, "load_insurance_metadata", lambda _: metadata)
    monkeypatch.setattr(insurance, "load_policy_snapshot", lambda _: policies)
    monkeypatch.setattr(insurance, "load_insurance_series", lambda *_: series)

    app = AppTest.from_function(_insurance_page).run()
    assert not app.exception
    app.selectbox[0].set_value("insurance").run()
    assert not app.exception
    assert len(app.selectbox) == 4
    assert any("Underwriting margin" in item.value for item in app.markdown)
    app.selectbox[1].set_value("A").run()
    assert not app.exception
    assert len(coverage_figure(series.iloc[0]).data) == 1