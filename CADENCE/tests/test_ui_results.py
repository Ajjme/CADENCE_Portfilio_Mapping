import json
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from cadence.ui.charts import SCENARIO_ORDER, cost_allocation_figure, scenario_labels, time_series_figure, wind_return_period_figure
from cadence.ui import results_data
from cadence.vulnerability.expected_damage import RETURN_PERIODS


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


def test_asset_options_place_portfolio_first_and_keep_all_assets() -> None:
    options = results_data.asset_options(["B-2", "A-1"])

    assert options == [results_data.PORTFOLIO_OPTION, "A-1", "B-2"]


def test_material_mix_label_counts_assets_in_canonical_order() -> None:
    materials = pd.DataFrame(
        {
            "asset_id": ["A-1", "A-2", "A-3", "A-3", "A-4"],
            "official_current_material_id": [
                "OFFICIAL_TILE", "OFFICIAL_ASPHALT", "OFFICIAL_ASPHALT",
                "OFFICIAL_ASPHALT", "OTHER",
            ],
        }
    )

    assert results_data.material_mix_label(materials) == (
        "Installed roofs · Asphalt 2 · Tile 1 · OTHER 1"
    )


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


def _wind_run(tmp_path: Path, monkeypatch, inconsistent: bool = False) -> Path:
    root = tmp_path / "schema_version=v0.4.0" / "run_id=wind-test"
    root.mkdir(parents=True)
    (root / "alternative_summary.parquet").touch()
    (root / "annual_alternative_analysis").mkdir()
    damage = root / "annual_scenario_damage"
    for year, factor in ((2026, 2), (2050, 3)):
        partition = damage / f"year={year}"
        partition.mkdir(parents=True)
        rows = []
        for asset_id in ("A-1", "A-2"):
            for scenario in SCENARIO_ORDER:
                row = {"asset_id": asset_id, "wind_grid_id": 65546}
                for index, period in enumerate(RETURN_PERIODS, start=1):
                    row[f"rp_{period}_3sec_gust"] = float(index * 10)
                    row[f"climate_scaled_rp_{period}_3sec_gust"] = float(index * 10 * factor)
                if inconsistent and asset_id == "A-1" and scenario == "NEW_METAL":
                    row["rp_10_3sec_gust"] = 11.0
                rows.append(row)
        pl.DataFrame(rows).write_parquet(partition / "part-00000.parquet")
    (root / "run_metadata.json").write_text(json.dumps({
        "run_id": "wind-test", "schema_version": "v0.4.0", "asset_count": 2,
        "annual_damage_path": str(damage),
        "run_config": {"start_year": 2026, "end_year": 2050},
    }), encoding="utf-8")
    monkeypatch.setattr(results_data, "ALTERNATIVE_RESULTS_ROOT", tmp_path)
    results_data.load_run_metadata.clear()
    results_data.load_wind_return_periods.clear()
    return root


def test_wind_return_periods_use_run_values_for_asset_and_portfolio(tmp_path, monkeypatch) -> None:
    root = _wind_run(tmp_path, monkeypatch)
    portfolio = results_data.load_wind_return_periods(str(root), results_data.PORTFOLIO_OPTION)
    asset = results_data.load_wind_return_periods(str(root), "A-1", 2050)

    assert portfolio["asset_id"].tolist() == ["A-1", "A-2"]
    assert portfolio["wind_grid_id"].tolist() == [65546, 65546]
    assert portfolio["rp_10"].tolist() == [10.0, 10.0]
    assert asset["asset_id"].tolist() == ["A-1"]
    assert asset["rp_10"].tolist() == [30.0]
    assert asset["rp_500"].tolist() == [180.0]


def test_wind_return_periods_reject_inconsistent_scenario_values(tmp_path, monkeypatch) -> None:
    root = _wind_run(tmp_path, monkeypatch, inconsistent=True)

    with pytest.raises(ValueError, match="missing or inconsistent"):
        results_data.load_wind_return_periods(str(root), "A-1")


def test_wind_return_periods_reject_missing_year_and_asset(tmp_path, monkeypatch) -> None:
    root = _wind_run(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="missing for 2027"):
        results_data.load_wind_return_periods(str(root), "A-1", 2027)
    with pytest.raises(ValueError, match="missing or inconsistent"):
        results_data.load_wind_return_periods(str(root), "unknown")


def test_wind_figure_interpolates_on_log_return_period_without_extrapolation() -> None:
    row = {"asset_id": "A-1", "wind_grid_id": 65546}
    row.update({f"rp_{period}": index * 10.0 for index, period in enumerate(RETURN_PERIODS, 1)})
    figure = wind_return_period_figure(pd.DataFrame([row, {**row, "asset_id": "A-2"}]), "Baseline")

    assert figure.layout.xaxis.type == "log"
    assert len(figure.data) == 4
    assert [figure.data[index].name for index in (0, 2)] == ["A-1", "A-2"]
    assert list(figure.data[1].x) == list(RETURN_PERIODS)
    assert list(figure.data[1].y) == [10, 20, 30, 40, 50, 60]
    assert figure.data[0].x[0] == 10
    assert figure.data[0].x[-1] == 500
    assert figure.data[0].x[8] == pytest.approx((10 * 25) ** 0.5)
    assert figure.data[0].y[8] == pytest.approx(15)


def _cost_run(tmp_path: Path, monkeypatch) -> tuple[Path, dict]:
    root = tmp_path / "roof_alternative_analysis" / "schema_version=v0.4.0" / "run_id=cost-test"
    partition = root / "annual_alternative_analysis" / "year=2026"
    partition.mkdir(parents=True)
    (root / "alternative_summary.parquet").touch()
    reference = tmp_path / "roof_alternative_analysis" / "economics_reference" / "schema_version=v0.3.0" / "run_id=reference"
    reference_partition = reference / "annual_roof_option_costs" / "year=2026"
    reference_partition.mkdir(parents=True)
    (reference / "run_metadata.json").write_text(
        json.dumps({"run_id": "reference", "schema_version": "v0.3.0"}), encoding="utf-8"
    )
    metadata = {
        "run_id": "cost-test", "schema_version": "v0.4.0", "asset_count": 2,
        "economics_reference_run_id": "reference",
        "temporary_tile_policy": {"policy_id": "temporary_tile_as_metal_with_1_2x_cost_v1"},
        "run_config": {
            "start_year": 2026, "end_year": 2050,
            "enabled_cost_streams": ["material", "labor", "disposal", "carbon"],
            "installed_cost_overrides": {
                material: {"material_share": share, "labor_share": 1 - share}
                for material, share in (("OFFICIAL_ASPHALT", 0.7), ("OFFICIAL_METAL", 0.6), ("OFFICIAL_TILE", 0.5))
            },
        },
    }
    (root / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    rows = []
    reference_rows = []
    for asset_id in ("A-1", "A-2"):
        for material in ("OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE"):
            reference_rows.append({
                "asset_id": asset_id, "year": 2026, "official_material_id": material,
                "source_material_usd_per_sqft": None if material == "OFFICIAL_ASPHALT" else 6.0,
                "source_labor_usd_per_sqft": 4.0,
            })
        for scenario, material in zip(SCENARIO_ORDER, (
            "OFFICIAL_ASPHALT", "OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE"
        )):
            event = scenario != "BASELINE_CURRENT"
            capex = 120.0 if scenario == "NEW_TILE" else 100.0 if event else 0.0
            repair = None if asset_id == "A-2" and scenario == "NEW_METAL" else 20.0
            rows.append({
                "asset_id": asset_id, "year": 2026, "scenario_id": scenario,
                "scenario_material_id": material, "official_current_material_id": "OFFICIAL_ASPHALT",
                "installation_event": event, "installation_event_capex_usd": capex,
                "annual_repair_cost_usd": repair, "expected_loss_of_use_usd": None,
                "enabled_event_disposal_cost_usd": 5.0 if event else 0.0,
                "enabled_event_carbon_cost_usd": 3.0 if event else 0.0,
                "annual_lifecycle_cash_flow_usd": capex + repair + 8.0 if repair is not None and event else repair,
                "active_cost_source": "class_installed_override_fallback" if scenario == "NEW_ASPHALT" else "source_computed_material_labor",
                "active_cost_fallback_applied": scenario == "NEW_ASPHALT",
            })
    pl.DataFrame(rows).write_parquet(partition / "part-00000.parquet")
    pl.DataFrame(reference_rows).write_parquet(reference_partition / "part-00000.parquet")
    monkeypatch.setattr(results_data, "ALTERNATIVE_RESULTS_ROOT", root.parents[1])
    results_data.load_run_metadata.clear()
    results_data.load_year_cost_rows.clear()
    return root, metadata


def test_year_cost_allocations_use_effective_capex_and_preserve_missing(tmp_path, monkeypatch) -> None:
    root, metadata = _cost_run(tmp_path, monkeypatch)
    rows = results_data.load_year_cost_rows(str(root), 2026, "A-1")
    asset = results_data.cost_allocations(rows, metadata, False).set_index("scenario_id")

    assert len(asset) == 4
    assert asset.loc["BASELINE_CURRENT", "material_usd"] == 0
    assert asset.loc["NEW_ASPHALT", "material_usd"] == pytest.approx(70)
    assert asset.loc["NEW_METAL", "labor_usd"] == pytest.approx(40)
    assert asset.loc["NEW_TILE", "material_usd"] == pytest.approx(72)
    assert asset.loc["NEW_TILE", "total_usd"] == pytest.approx(148)
    assert asset.loc["NEW_METAL", "loss_of_use_usd"] == 0
    assert asset.loc["NEW_TILE", "allocation_estimated"]

    portfolio = results_data.cost_allocations(
        results_data.load_year_cost_rows(str(root), 2026, results_data.PORTFOLIO_OPTION), metadata, True
    ).set_index("scenario_id")
    assert portfolio.loc["NEW_TILE", "total_usd"] == pytest.approx(296)
    assert pd.isna(portfolio.loc["NEW_METAL", "repair_usd"])
    assert pd.isna(portfolio.loc["NEW_METAL", "total_usd"])
    with pytest.raises(ValueError, match="outside"):
        results_data.load_year_cost_rows(str(root), 2025, "A-1")


def test_cost_allocations_no_event_missing_stream_and_chart(tmp_path, monkeypatch) -> None:
    root, metadata = _cost_run(tmp_path, monkeypatch)
    rows = results_data.load_year_cost_rows(str(root), 2026, "A-1")
    rows.loc[rows["scenario_id"] == "NEW_METAL", "installation_event"] = False
    rows.loc[rows["scenario_id"] == "NEW_METAL", "installation_event_capex_usd"] = 0
    metadata["run_config"]["enabled_cost_streams"].append("loss_of_use")
    costs = results_data.cost_allocations(rows, metadata, False).set_index("scenario_id")

    assert costs.loc["NEW_METAL", "material_usd"] == 0
    assert costs.loc["NEW_METAL", "labor_usd"] == 0
    assert pd.isna(costs.loc["NEW_METAL", "total_usd"])
    figure = cost_allocation_figure(costs.reset_index(), "Test", scenario_labels("OFFICIAL_ASPHALT"))
    assert figure.layout.barmode == "stack"
    assert len(figure.data) == 7
    assert figure.data[-1].text[2] == "Incomplete"


def test_year_cost_allocations_reject_missing_reference(tmp_path, monkeypatch) -> None:
    root, metadata = _cost_run(tmp_path, monkeypatch)
    reference = root.parents[1] / "economics_reference" / "schema_version=v0.3.0" / "run_id=reference"
    (reference / "run_metadata.json").unlink()

    with pytest.raises(ValueError, match="economics reference costs are unavailable"):
        results_data.load_year_cost_rows(str(root), 2026, "A-1")


def test_map_best_is_metric_specific_and_preserves_negative_and_missing_values():
    summary = pd.DataFrame({
        "asset_id": ["A"] * 3 + ["B"] * 3,
        "scenario_id": ["NEW_ASPHALT", "NEW_METAL", "NEW_TILE"] * 2,
        "net_present_value_usd": [-1., -2., -3., 10., None, 20.],
        "cumulative_avoided_damage_usd": [1., 5., 5., 2., 3., 4.],
    })
    geography = pd.DataFrame({"asset_id": ["A", "B"], "state_code": ["CA", "CA"]})
    npv = results_data.map_outcomes(summary, geography, "net_present_value_usd", "BEST")
    damage = results_data.map_outcomes(summary, geography, "cumulative_avoided_damage_usd", "BEST")
    assert npv.iloc[0]["scenario_id"] == "NEW_ASPHALT"
    assert npv.iloc[0]["net_present_value_usd"] == -1
    assert pd.isna(npv.iloc[1]["net_present_value_usd"])
    assert damage["scenario_id"].tolist() == ["NEW_METAL", "NEW_TILE"]
    total = results_data.regional_map_outcomes(npv, "net_present_value_usd", "State", False).iloc[0]
    assert pd.isna(total["value"]) and total["missing_count"] == 1
    average = results_data.regional_map_outcomes(damage, "cumulative_avoided_damage_usd", "State", True).iloc[0]
    assert average["value"] == 4.5
    tile = results_data.map_outcomes(summary, geography, "net_present_value_usd", "NEW_TILE")
    assert tile["net_present_value_usd"].tolist() == [-3., 20.]


def test_map_geography_comes_from_saved_run_without_active_session(tmp_path, monkeypatch):
    root = _wind_run(tmp_path, monkeypatch)
    partition = root / "annual_scenario_damage/year=2026/part-00000.parquet"
    rows = pl.read_parquet(partition).with_columns(
        pl.Series("scenario_id", list(SCENARIO_ORDER) * 2),
        pl.lit(35.).alias("latitude"), pl.lit(-80.).alias("longitude"),
        pl.lit("28001").alias("zip_code"), pl.lit("37167").alias("county_fips"),
        pl.lit("NC").alias("state_code"),
    )
    rows.write_parquet(partition)
    results_data.load_map_geography.clear()
    geography = results_data.load_map_geography(str(root))
    assert geography["asset_id"].tolist() == ["A-1", "A-2"]
    assert geography["state_code"].tolist() == ["NC", "NC"]
    rows.with_columns(pl.when(pl.col("scenario_id") == "NEW_METAL").then(36.).otherwise(pl.col("latitude")).alias("latitude")).write_parquet(partition)
    results_data.load_map_geography.clear()
    with pytest.raises(ValueError, match="inconsistent"):
        results_data.load_map_geography(str(root))


def test_results_navigation_includes_market_study(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from cadence.ui.pages import results

    monkeypatch.setattr(results, "_select_run", lambda: "/unused")
    monkeypatch.setattr(results, "load_run_metadata", lambda _: {
        "run_id": "navigation", "schema_version": "v0.4.0", "asset_count": 1,
    })
    monkeypatch.setattr(results, "load_summary", lambda _: pd.DataFrame({"asset_id": ["A"]}))
    for name in ("_render_overview", "_render_time_series", "_render_alternative_summary",
                 "_render_cost_allocations", "_render_wind_return_period", "_render_run_information"):
        monkeypatch.setattr(results, name, lambda *args: None)
    def results_page():
        from cadence.ui.pages import results

        results.render()

    app = AppTest.from_function(results_page).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Overview", "Time Series", "Alternative Summary", "Cost Allocations",
        "Wind Return Period", "Market Study", "Run Information",
    ]
    assert any("Experimental study" in warning.value for warning in app.warning)
    assert any("matching active session" in message.value for message in app.info)


def test_run_discovery_sees_newly_published_runs(tmp_path):
    assert results_data.discover_runs(str(tmp_path)) == []
    root = tmp_path / "schema_version=v0.4.0/run_id=new"
    root.mkdir(parents=True)
    (root / "run_metadata.json").write_text(json.dumps({"run_id": "new"}), encoding="utf-8")
    assert [run["run_id"] for run in results_data.discover_runs(str(tmp_path))] == ["new"]