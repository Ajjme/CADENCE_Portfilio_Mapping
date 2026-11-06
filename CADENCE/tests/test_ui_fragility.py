import json
import os
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from streamlit.testing.v1 import AppTest

from cadence.economics.temporary_policies import TEMPORARY_TILE_POLICY_ID
from cadence.reference_data.fragility import (
    CURVE_AGGREGATION_METHOD,
    CURVE_KEYS,
    FRAGILITY_SNAPSHOT_VERSION,
    MATERIAL_PROXY_IDS,
    load_fragility_curves,
)
from cadence.reference_data.year1_damage import _fragility_identity
from cadence.ui import results_data
from cadence.ui.charts import SCENARIO_ORDER, fragility_curve_figure
from cadence.ui.workbooks import sha256_file
from cadence.vulnerability.annual_damage import GUST_COLUMNS, build_annual_scenario_damage
from cadence.vulnerability.expected_damage import RETURN_PERIODS


@pytest.fixture
def curve_run(tmp_path, monkeypatch):
    def create(snapshot=True):
        root = tmp_path / "schema_version=v0.4.0" / "run_id=curves"
        root.mkdir(parents=True)
        reference = tmp_path / "reference"
        state_rows = []
        for year in (2026, 2027):
            for asset, current, terrain in (("A-1", "OFFICIAL_TILE", 1), ("B-2", "OFFICIAL_ASPHALT", 3)):
                for scenario in SCENARIO_ORDER:
                    baseline = scenario == "BASELINE_CURRENT"
                    age = (35 if year == 2026 else 0) if baseline and asset == "A-1" else (
                        10 + year - 2026 if baseline else year - 2026
                    )
                    material = current if baseline else f"OFFICIAL_{scenario.removeprefix('NEW_')}"
                    state_rows.append({
                        "asset_id": asset, "year": year, "scenario_id": scenario,
                        "scenario_material_id": material, "roof_age_years": age,
                        "lookup_roof_age": min(age + 1, 30), "age_capped": age + 1 > 30,
                        "installation_event": age == 0,
                        "burnout_replacement_event": baseline and age == 0,
                        "temporary_tile_metal_proxy_applied": scenario == "NEW_TILE",
                    })
        state = pl.DataFrame(state_rows)
        hazard = pl.DataFrame({
            "asset_id": ["A-1", "B-2"], "wind_grid_id": [1, 2],
            "climate_zone": ["3A", "3A"], "terrain_id": [1, 3],
            **{column: [60.0 + index * 10, 65.0 + index * 10] for index, column in enumerate(GUST_COLUMNS)},
        })
        effective = state.with_columns(
            pl.when(pl.col("scenario_id") == "NEW_TILE").then(pl.lit("OFFICIAL_METAL"))
            .otherwise(pl.col("scenario_material_id")).alias("scenario_material_id")
        )
        keys = effective.select(
            "asset_id", "lookup_roof_age", pl.col("scenario_material_id").alias("source_material_id")
        ).join(hazard.select("asset_id", "climate_zone", "terrain_id"), on="asset_id").select(CURVE_KEYS).unique()
        for age in keys["lookup_roof_age"].unique():
            partition = reference / "3A" / f"age_{age:02d}"
            partition.mkdir(parents=True)
            definitions, points, attributes = [], [], []
            for terrain in (1, 3):
                for index, proxy in enumerate(MATERIAL_PROXY_IDS.values(), 1):
                    for variant, factor in enumerate((0.8, 1.2)):
                        curve_id = terrain * 100 + index * 10 + variant
                        definitions.append({"curve_id": curve_id, "damage_type": "building_loss", "building_type": proxy})
                        attributes.append({"curve_id": curve_id, "key": "terrain_id", "value": str(terrain)})
                        loss = age / 60 * (0.7 + index * 0.1) * factor
                        points.extend({"curve_id": curve_id, "x": wind, "y": value}
                                      for wind, value in ((50.0, 0.0), (100.0, loss / 2), (150.0, loss)))
            for name, records in (("curves_hu", definitions), ("curve_points_hu", points), ("curve_attributes_hu", attributes)):
                pl.DataFrame(records).write_parquet(partition / f"{name}.parquet")
        curves = load_fragility_curves(reference, keys)
        factors = pl.DataFrame([
            {"wind_grid_id": grid, "year": year, "climate_scale_factor": 1.1, "climate_scale_rule": "source_year"}
            for grid in (1, 2) for year in (2026, 2027)
        ])
        damage = build_annual_scenario_damage(effective, hazard, reference, factors, curves=curves).with_columns(
            pl.when(pl.col("scenario_id") == "NEW_TILE").then(pl.lit("OFFICIAL_TILE"))
            .otherwise(pl.col("scenario_material_id")).alias("scenario_material_id")
        )
        for artifact, frame in (("annual_scenario_state", state), ("annual_scenario_damage", damage)):
            for year in (2026, 2027):
                partition = root / artifact / f"year={year}"
                partition.mkdir(parents=True)
                frame.filter(pl.col("year") == year).write_parquet(partition / "part.parquet")
        (root / "annual_alternative_analysis").mkdir()
        state.select("asset_id", "scenario_id").unique().write_parquet(root / "alternative_summary.parquet")
        metadata = {
            "run_id": "curves", "schema_version": "v0.4.0", "asset_count": 2,
            "run_config": {"start_year": 2026, "end_year": 2027},
            "annual_state_path": str(root / "annual_scenario_state"),
            "annual_damage_path": str(root / "annual_scenario_damage"),
            "fragility_identity": _fragility_identity(keys, reference),
            "temporary_tile_policy": {
                "policy_id": TEMPORARY_TILE_POLICY_ID,
                "lifecycle_and_vulnerability_source": "NEW_METAL",
            },
        }
        if snapshot:
            path = root / "fragility_curves.parquet"
            curves.write_parquet(path)
            metadata.update({
                "fragility_snapshot_version": FRAGILITY_SNAPSHOT_VERSION,
                "fragility_curves_path": str(path),
                "fragility_curves_checksum": sha256_file(path),
                "fragility_curve_point_count": curves.height,
                "fragility_curve_key_count": curves.select(CURVE_KEYS).unique().height,
                "fragility_curve_aggregation_method": CURVE_AGGREGATION_METHOD,
            })
        _save_metadata(root, metadata)
        monkeypatch.setattr(results_data, "ALTERNATIVE_RESULTS_ROOT", tmp_path)
        monkeypatch.setattr(results_data, "FRAGILITY_ROOT", reference)
        results_data._load_saved_fragility_curves.clear()
        results_data._load_verified_reference_curves.clear()
        return root, metadata, reference, curves, damage
    return create


def _save_metadata(root, metadata):
    (root / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    results_data.load_run_metadata.clear()


def test_snapshot_reopens_without_references_and_reproduces_damage(curve_run, monkeypatch):
    root, _, _, source, damage = curve_run()
    monkeypatch.setattr(results_data, "FRAGILITY_ROOT", root / "unavailable")
    for year in (2026, 2027):
        portfolio = results_data.load_fragility_results(str(root), results_data.PORTFOLIO_OPTION, year)
        assert len(portfolio) == 2 * 4 * 3
        assert portfolio["curve_provenance"].unique().tolist() == ["Saved curve snapshot"]
        for (asset, scenario), points in portfolio.groupby(["asset_id", "scenario_id"]):
            row = damage.filter(
                (pl.col("asset_id") == asset) & (pl.col("scenario_id") == scenario) & (pl.col("year") == year)
            ).row(0, named=True)
            original = source.filter(
                (pl.col("climate_zone") == row["climate_zone"])
                & (pl.col("terrain_id") == row["terrain_id"])
                & (pl.col("lookup_roof_age") == row["lookup_roof_age"])
                & (pl.col("fragility_proxy_id") == row["fragility_proxy_id"])
            ).sort("wind_speed_mph")
            assert points["building_loss_ratio"].tolist() == original["building_loss_ratio"].to_list()
            assert points["source_curve_count"].tolist() == [2] * 3
            actual = np.interp(
                [row[f"climate_scaled_{column}"] for column in GUST_COLUMNS],
                points["wind_speed_mph"], points["building_loss_ratio"],
            )
            assert actual.tolist() == pytest.approx([row[f"rp_{period}_damage_ratio"] for period in RETURN_PERIODS])
    asset = results_data.load_fragility_results(str(root), "A-1", 2026)
    baseline = asset.loc[asset["scenario_id"] == "BASELINE_CURRENT"].iloc[0]
    assert (baseline["roof_age_years"], baseline["lookup_roof_age"], baseline["age_capped"]) == (35, 30, True)
    assert baseline["fragility_proxy_id"] == "MSF1"
    assert asset.loc[asset["scenario_id"] == "NEW_TILE", "fragility_proxy_id"].unique().tolist() == ["SERBL"]
    replacement = results_data.load_fragility_results(str(root), "A-1", 2027)
    baseline = replacement.loc[replacement["scenario_id"] == "BASELINE_CURRENT"].iloc[0]
    assert (baseline["roof_age_years"], baseline["lookup_roof_age"], baseline["burnout_replacement_event"]) == (0, 1, True)


def test_legacy_checks_full_run_identity_even_after_cached_display(curve_run):
    root, _, reference, _, _ = curve_run(snapshot=False)
    first = results_data.load_fragility_results(str(root), "A-1", 2026)
    assert first["curve_provenance"].unique().tolist() == ["Identity-verified legacy reference"]
    future_source = reference / "3A" / "age_02" / "curve_points_hu.parquet"
    stat = future_source.stat()
    os.utime(future_source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with pytest.raises(ValueError, match="no longer match"):
        results_data.load_fragility_results(str(root), "A-1", 2026)


@pytest.mark.parametrize("problem", ["missing", "corrupt", "unsupported", "counts", "points", "missing_key"])
def test_invalid_snapshot_never_falls_back_to_references(curve_run, problem):
    root, metadata, _, curves, _ = curve_run()
    snapshot = root / "fragility_curves.parquet"
    if problem == "missing":
        snapshot.unlink()
    elif problem == "corrupt":
        snapshot.write_bytes(b"corrupt")
    elif problem == "unsupported":
        metadata["fragility_snapshot_version"] = "future"
    elif problem == "counts":
        metadata["fragility_curve_point_count"] += 1
    else:
        if problem == "points":
            curves = curves.with_columns(pl.lit(float("nan")).alias("building_loss_ratio"))
        else:
            curves = curves.filter(pl.col("lookup_roof_age") != 30)
            metadata["fragility_curve_point_count"] = curves.height
            metadata["fragility_curve_key_count"] = curves.select(CURVE_KEYS).unique().height
        curves.write_parquet(snapshot)
        metadata["fragility_curves_checksum"] = sha256_file(snapshot)
    _save_metadata(root, metadata)
    with pytest.raises(ValueError, match="fragility"):
        results_data.load_fragility_results(str(root), "A-1", 2026)


@pytest.mark.parametrize("problem", ["missing_scenario", "duplicate", "mapping", "proxy", "age", "missing_year"])
def test_inconsistent_saved_rows_are_rejected(curve_run, problem):
    root, _, _, _, damage = curve_run()
    path = root / "annual_scenario_damage" / "year=2026" / "part.parquet"
    rows = damage.filter(pl.col("year") == 2026)
    if problem == "missing_year":
        path.unlink()
    else:
        if problem == "missing_scenario":
            rows = rows.filter(pl.col("scenario_id") != "NEW_TILE")
        elif problem == "duplicate":
            rows = pl.concat([rows, rows.head(1)])
        elif problem == "mapping":
            rows = rows.with_columns(pl.lit("unknown").alias("fragility_mapping_version"))
        elif problem == "proxy":
            rows = rows.with_columns(pl.lit("WSF1").alias("fragility_proxy_id"))
        else:
            rows = rows.with_columns(pl.lit(2).alias("lookup_roof_age"))
        rows.write_parquet(path)
    with pytest.raises(ValueError):
        results_data.load_fragility_results(str(root), results_data.PORTFOLIO_OPTION, 2026)


def test_invalid_asset_or_year_is_rejected(curve_run):
    root, _, _, _, _ = curve_run()
    with pytest.raises(ValueError, match="modeled years"):
        results_data.load_fragility_results(str(root), "A-1", 2050)
    with pytest.raises(ValueError, match="missing"):
        results_data.load_fragility_results(str(root), "unknown", 2026)


def test_figure_preserves_all_source_knots_and_coincident_curves(curve_run):
    root, _, _, _, _ = curve_run()
    points = results_data.load_fragility_results(str(root), results_data.PORTFOLIO_OPTION, 2026)
    figure = fragility_curve_figure(points, "Portfolio")
    assert len(figure.data) == 8
    assert figure.layout.xaxis.type == "linear"
    assert figure.layout.yaxis.range == (0, 1)
    assert figure.layout.yaxis.tickformat == ".0%"
    assert len({trace.legendgroup for trace in figure.data}) == 8
    for trace in figure.data:
        assert list(trace.x) == [50.0, 100.0, 150.0]
        assert trace.mode == "lines+markers"
        assert trace.line.shape == "linear"
        assert trace.customdata[0][9] == 2
        assert "Modeled building loss" in trace.hovertemplate
    for start in (0, 4):
        assert len({trace.line.dash for trace in figure.data[start:start + 4]}) == 4
        assert len({trace.line.color for trace in figure.data[start:start + 4]}) == 1
        assert list(figure.data[start + 2].y) == list(figure.data[start + 3].y)
    asset = fragility_curve_figure(points.loc[points["asset_id"] == "A-1"], "Asset")
    assert len(asset.data) == 4


def test_tab_defaults_year_and_handles_selection_and_unavailable_data(curve_run, monkeypatch):
    from cadence.ui.pages import results

    root, metadata, _, _, _ = curve_run()
    monkeypatch.setattr(results, "_select_run", lambda: str(root))
    monkeypatch.setattr(results, "load_summary", lambda _: pl.DataFrame({"asset_id": ["A-1", "B-2"]}).to_pandas())
    for name in ("_render_overview", "_render_time_series", "_render_alternative_summary",
                 "_render_cost_allocations", "_render_wind_return_period", "_render_market_study", "_render_run_information"):
        monkeypatch.setattr(results, name, lambda *args: None)

    def results_page():
        from cadence.ui.pages import results
        results.render()

    app = AppTest.from_function(results_page).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs][4:6] == ["Wind Return Period", "Roof Fragility Curves"]
    year_key = f"results_fragility_year_{metadata['run_id']}"
    assert app.selectbox(key=year_key).value == 2026
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(chart["data"]) == 8
    app.selectbox(key="results_asset_curves").select("A-1")
    app.selectbox(key=year_key).select(2027).run()
    assert not app.exception
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(chart["data"]) == 4
    assert "2027" in chart["layout"]["title"]["text"]
    (root / "fragility_curves.parquet").unlink()
    app.run()
    assert not app.exception
    assert any("Roof fragility curves are unavailable" in item.value for item in app.warning)
    assert len(app.tabs) == 8
