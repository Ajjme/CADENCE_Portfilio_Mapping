import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

import cadence.economics.run_export as run_export
from cadence.economics.run_export import build_run_workbook

SCENARIOS = ("BASELINE_CURRENT", "NEW_METAL")


def _write_run(root: Path) -> Path:
    run = root / "schema_version=v0.4.0" / "run_id=export-test"
    run.mkdir(parents=True)
    (run / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_id": "export-test",
                "schema_version": "v0.4.0",
                "run_timestamp": "2026-11-08T17:00:00+00:00",
                "asset_count": 2,
                "dollar_basis": "real_2026_usd",
                "run_config": {"start_year": 2026, "end_year": 2027, "discount_rate": 0.03},
                "climate_delta_source_years": [2025, 2050],
                "summary_path": "/mount/src/somewhere/alternative_summary.parquet",
            }
        ),
        encoding="utf-8",
    )
    summary = []
    for asset_id, npv in (("A-1", 100.0), ("A-2", 50.0)):
        for scenario in SCENARIOS:
            summary.append(
                {
                    "asset_id": asset_id,
                    "scenario_id": scenario,
                    "burnout_replacement_count": 1,
                    "cumulative_avoided_damage_usd": npv,
                    "cumulative_discounted_avoided_damage_usd": npv,
                    "cumulative_net_benefit_usd": npv,
                    "net_present_value_usd": npv if scenario == "NEW_METAL" else None,
                    "active_cost_fallback_applied": False,
                    "repair_cost_incomplete": False,
                    "climate_risk_total_incomplete": False,
                    "event_cost_incomplete": False,
                }
            )
    pl.DataFrame(summary).write_parquet(run / "alternative_summary.parquet")
    for year in (2026, 2027):
        partition = run / "annual_alternative_analysis" / f"year={year}"
        partition.mkdir(parents=True)
        pl.DataFrame(
            {
                "asset_id": ["A-2", "A-1", "A-2", "A-1"],
                "scenario_id": ["NEW_METAL", "NEW_METAL", "BASELINE_CURRENT", "BASELINE_CURRENT"],
                "annual_avoided_damage_usd": [1.0, 2.0, 0.0, 0.0],
                "cost_sources": [["material"], ["material", "labor"], [], []],
                "computed_at": [datetime(2026, 11, 8, 12, tzinfo=timezone.utc)] * 4,
            }
        ).write_parquet(partition / "part-0.parquet")
    return run


def _read(workbook: bytes) -> dict:
    return pd.read_excel(io.BytesIO(workbook), sheet_name=None)


def test_workbook_has_every_sheet_with_the_run_results(tmp_path: Path) -> None:
    sheets = _read(build_run_workbook(_write_run(tmp_path)))

    assert list(sheets) == ["About", "Portfolio summary", "Asset summary", "Annual results", "Run settings"]
    assert len(sheets["Asset summary"]) == 4
    annual = sheets["Annual results"]
    assert len(annual) == 8
    assert annual[["asset_id", "scenario_id", "year"]].head(2).values.tolist() == [
        ["A-1", "BASELINE_CURRENT", 2026],
        ["A-1", "BASELINE_CURRENT", 2027],
    ]
    assert json.loads(annual["cost_sources"].iloc[-1]) == ["material"]
    about = dict(sheets["About"][["Item", "Value"]].dropna().values.tolist())
    assert about["Run ID"] == "export-test"
    assert about["Years"] == "2026-2027"
    assert about["Dollars"] == "Real 2026 USD"


def test_portfolio_totals_keep_incomplete_values_blank(tmp_path: Path) -> None:
    portfolio = _read(build_run_workbook(_write_run(tmp_path)))["Portfolio summary"].set_index("scenario_id")

    assert portfolio.loc["NEW_METAL", "net_present_value_usd"] == 150.0
    assert pd.isna(portfolio.loc["BASELINE_CURRENT", "net_present_value_usd"])
    assert portfolio.loc["NEW_METAL", "asset_count"] == 2


def test_settings_flatten_the_metadata_and_leave_out_server_paths(tmp_path: Path) -> None:
    settings = _read(build_run_workbook(_write_run(tmp_path)))["Run settings"]
    values = dict(settings[["Setting", "Value"]].values.tolist())

    assert values["run_config.discount_rate"] == 0.03
    assert json.loads(values["climate_delta_source_years"]) == [2025, 2050]
    assert not any(str(key).endswith("_path") for key in values)


def test_missing_annual_results_are_reported(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    shutil.rmtree(run / "annual_alternative_analysis")

    with pytest.raises(ValueError, match="annual_alternative_analysis"):
        build_run_workbook(run)


def test_runs_too_big_for_one_sheet_are_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_export, "EXCEL_MAX_ROWS", 3)

    with pytest.raises(ValueError, match="more than one Excel sheet holds"):
        build_run_workbook(_write_run(tmp_path))
