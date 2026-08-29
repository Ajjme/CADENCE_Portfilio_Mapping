import json
from pathlib import Path

import pandas as pd
import pytest

from cadence.ui.charts import SCENARIO_ORDER, scenario_labels, time_series_figure
from cadence.ui import results_data


def test_rejects_unsupported_result_schema(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "schema_version=v0.1.0" / "run_id=historic"
    root.mkdir(parents=True)
    (root / "run_metadata.json").write_text(
        json.dumps({"run_id": "historic", "schema_version": "v0.1.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(results_data, "ALTERNATIVE_RESULTS_ROOT", tmp_path)
    results_data.load_run_metadata.clear()

    with pytest.raises(ValueError, match="unsupported result schema"):
        results_data.load_run_metadata(str(root))


def test_portfolio_summary_preserves_incomplete_value_as_gap() -> None:
    rows = []
    for asset_id, npv in (("A-1", 10.0), ("A-2", None)):
        rows.append(
            {
                "asset_id": asset_id,
                "scenario_id": "NEW_METAL",
                "burnout_replacement_count": 0,
                "cumulative_avoided_damage_usd": npv,
                "cumulative_discounted_avoided_damage_usd": npv,
                "cumulative_net_benefit_usd": npv,
                "net_present_value_usd": npv,
                "active_cost_fallback_applied": False,
                "repair_cost_incomplete": npv is None,
                "climate_risk_total_incomplete": False,
                "event_cost_incomplete": False,
            }
        )

    result = results_data.portfolio_summary(pd.DataFrame(rows)).iloc[0]

    assert pd.isna(result["net_present_value_usd"])
    assert bool(result["repair_cost_incomplete"]) is True


def test_time_series_contains_four_scenarios_and_event_traces() -> None:
    rows = []
    for scenario in SCENARIO_ORDER:
        rows.append(
            {
                "year": 2026,
                "scenario_id": scenario,
                "metric_value": 100.0,
                "installation_event": True,
                "initial_installation_event": scenario != "BASELINE_CURRENT",
                "burnout_replacement_event": False,
            }
        )
    figure = time_series_figure(
        pd.DataFrame(rows), "Test", scenario_labels("OFFICIAL_METAL")
    )

    assert len(figure.data) == 8
    assert [trace.name for trace in figure.data[::2]] == [
        "Installed roof Metal", "New asphalt", "New metal", "New tile"
    ]