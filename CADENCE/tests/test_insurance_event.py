import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from streamlit.testing.v1 import AppTest

from cadence.insurance.analysis import SCENARIOS
from cadence.insurance.event_analysis import EventSettings, calculate_event, summarize_event
from cadence.insurance.event_pipeline import discover_events, load_event, publish_event
from cadence.ui import insurance_event_page
from cadence.ui.insurance_event_page import build_event_map


def inputs():
    return pl.DataFrame([
        {
            "asset_id": asset, "scenario_id": scenario, "year": 2026,
            "state_code": state, "latitude": latitude, "longitude": -90.0,
            "active_installed_capex_usd": 100_000.0,
            "policy_id": "Shared", "insured_value": 30_000.0,
            "deductible_amount": 5_000.0, "deductible_type": "standard", "peril": "wind",
            "current_premium": None,
            "climate_scaled_rp_100_3sec_gust": 100.0,
            "climate_scaled_rp_200_3sec_gust": 120.0,
            "climate_scaled_rp_500_3sec_gust": 150.0,
            "rp_100_damage_ratio": 0.4, "rp_200_damage_ratio": 0.5, "rp_500_damage_ratio": 0.9,
        }
        for asset, state, latitude in (("A", "TX", 30.0), ("B", "FL", 29.0))
        for scenario in sorted(SCENARIOS)
    ])


def curves():
    return pl.DataFrame([
        {"asset_id": asset, "scenario_id": scenario, "wind_speed_mph": x, "building_loss_ratio": y}
        for asset in ("A", "B") for scenario in sorted(SCENARIOS)
        for x, y in ((100.0, 0.0), (130.0, 0.2), (150.0, 1.0))
    ])


def test_exact_event_not_probability_weighted_and_missing_premium_is_allowed():
    rows = calculate_event(inputs(), EventSettings(year=2026))
    assert rows["gross_event_damage_usd"].to_list() == [40_000.0] * 8
    assert rows["insured_event_payout_usd"].to_list() == [30_000.0] * 8
    totals = summarize_event(rows)
    assert totals["gross_event_damage_usd"].to_list() == [80_000.0] * 4
    assert totals["insured_event_payout_usd"].to_list() == [60_000.0] * 4


@pytest.mark.parametrize("period,damage", [(100, .4), (200, .5), (500, .9)])
def test_saved_event_ratios(period, damage):
    result = calculate_event(inputs(), EventSettings(year=2026, return_period=period))
    assert result["event_damage_ratio"].to_list() == [damage] * 8


def test_300_interpolates_gust_then_nonlinear_curve():
    result = calculate_event(inputs(), EventSettings(year=2026, return_period=300), curves())
    gust = 120 + np.log(1.5) / np.log(2.5) * 30
    damage = .2 + (gust - 130) / 20 * .8
    assert result["local_gust_mph"][0] == pytest.approx(gust)
    assert result["event_damage_ratio"][0] == pytest.approx(damage)
    assert damage != pytest.approx(.5 + np.log(1.5) / np.log(2.5) * .4)
    assert result["gust_estimated"].all()


def test_300_effective_scenario_curve_and_clamp():
    data = inputs().with_columns(pl.lit(200.0).alias("climate_scaled_rp_200_3sec_gust"),
                                 pl.lit(250.0).alias("climate_scaled_rp_500_3sec_gust"))
    effective = curves().with_columns(
        pl.when(pl.col("scenario_id") == "NEW_METAL").then(pl.col("building_loss_ratio") * .5)
        .otherwise(pl.col("building_loss_ratio")).alias("building_loss_ratio")
    )
    rows = calculate_event(data, EventSettings(year=2026, return_period=300), effective)
    assert rows["event_curve_clamped"].all()
    assert rows.filter(pl.col("scenario_id") == "NEW_METAL")["event_damage_ratio"].to_list() == [.5, .5]


def test_states_unaffected_zero_and_independent_completeness():
    data = inputs().with_columns(
        pl.when(pl.col("asset_id") == "B").then(None).otherwise(pl.col("insured_value")).alias("insured_value")
    )
    rows = calculate_event(data, EventSettings(year=2026, states=("TX",)))
    assert rows.filter(pl.col("asset_id") == "B")["insured_event_payout_usd"].to_list() == [0] * 4
    assert summarize_event(rows)["insured_event_payout_usd"].to_list() == [30_000.0] * 4
    all_rows = calculate_event(data, EventSettings(year=2026))
    totals = summarize_event(all_rows)
    assert totals["gross_event_damage_usd"].to_list() == [80_000.0] * 4
    assert totals["insured_event_payout_usd"].null_count() == 4
    assert totals["insured_event_payout_usd_missing_count"].to_list() == [1] * 4
    states = summarize_event(all_rows, by_state=True)
    assert states.filter(pl.col("state_code") == "TX")["insured_event_payout_usd"].null_count() == 0
    assert states.filter(pl.col("state_code") == "FL")["insured_event_payout_usd"].null_count() == 4


def test_missing_cost_and_wind_do_not_create_zeroes():
    for field in ("active_installed_capex_usd", "climate_scaled_rp_100_3sec_gust", "rp_100_damage_ratio"):
        rows = calculate_event(inputs().with_columns(pl.lit(None).alias(field)), EventSettings(year=2026))
        assert rows["gross_event_damage_usd"].null_count() == 8
        assert rows["physical_issue"].null_count() == 0


@pytest.mark.parametrize("damage,payout", [(0.0, 0), (.01, 0), (.1, 5000), (1.0, 30000)])
def test_deductible_floor_and_cap(damage, payout):
    rows = calculate_event(inputs().with_columns(pl.lit(damage).alias("rp_100_damage_ratio")), EventSettings(year=2026))
    assert rows["insured_event_payout_usd"].to_list() == [payout] * 8


@pytest.mark.parametrize("field,value", [
    ("deductible_type", "percent"), ("peril", "hail"), ("policy_id", None),
    ("insured_value", -1.0), ("deductible_amount", None),
])
def test_unsupported_event_policy_keeps_gross(field, value):
    rows = calculate_event(inputs().with_columns(pl.lit(value).alias(field)), EventSettings(year=2026))
    assert rows["gross_event_damage_usd"].null_count() == 0
    assert rows["insured_event_payout_usd"].null_count() == 8


def test_invalid_scope_and_grain():
    with pytest.raises(ValueError, match="at least one"):
        EventSettings(year=2026, states=())
    with pytest.raises(ValueError, match="No assets"):
        calculate_event(inputs(), EventSettings(year=2026, states=("CA",)))
    unknown = inputs().with_columns(pl.lit(None, dtype=pl.String).alias("state_code"))
    with pytest.raises(ValueError, match="unknown asset states"):
        calculate_event(unknown, EventSettings(year=2026, states=("TX",)))
    assert set(summarize_event(calculate_event(unknown, EventSettings(year=2026)), by_state=True)["state_code"]) == {"Unknown"}
    with pytest.raises(ValueError, match="duplicate"):
        calculate_event(pl.concat([inputs(), inputs().head(1)]), EventSettings(year=2026))
    with pytest.raises(ValueError, match="four scenarios"):
        calculate_event(inputs().slice(1), EventSettings(year=2026))
    with pytest.raises(ValueError, match="selected year"):
        calculate_event(inputs(), EventSettings(year=2027))
    with pytest.raises(ValueError):
        EventSettings(year=2026, return_period=250)


@pytest.mark.parametrize("field,value", [
    ("rp_100_damage_ratio", float("nan")), ("rp_100_damage_ratio", 1.1),
    ("active_installed_capex_usd", -1.), ("climate_scaled_rp_100_3sec_gust", float("inf")),
])
def test_invalid_physical_values_fail(field, value):
    with pytest.raises(ValueError):
        calculate_event(inputs().with_columns(pl.lit(value).alias(field)), EventSettings(year=2026))


def test_300_rejects_missing_curves_and_reversed_gusts():
    with pytest.raises(ValueError, match="verified effective"):
        calculate_event(inputs(), EventSettings(year=2026, return_period=300))
    with pytest.raises(ValueError, match="500-year"):
        calculate_event(inputs().with_columns(pl.lit(110.0).alias("climate_scaled_rp_500_3sec_gust")),
                        EventSettings(year=2026, return_period=300), curves())


def test_immutable_event_identity_and_reopen(tmp_path):
    provenance = {"physical_run_id": "physical", "insurance_run_id": "insurance"}
    settings = EventSettings(year=2026, states=("TX", "FL"))
    first = publish_event(inputs(), settings, provenance, tmp_path)
    second = publish_event(inputs(), EventSettings(year=2026, states=("FL", "TX", "TX")), provenance, tmp_path)
    assert second["cache_hit"] and second["run_id"] == first["run_id"]
    assert first["run_id"] == load_event(Path(first["run_root"]), tmp_path)[0]["run_id"]
    for changed in (EventSettings(year=2026), EventSettings(year=2026, return_period=200),
                    EventSettings(year=2026, states=("TX",))):
        assert publish_event(inputs(), changed, provenance, tmp_path)["run_id"] != first["run_id"]
    assert publish_event(inputs(), settings, {**provenance, "policy_checksum": "changed"}, tmp_path)["run_id"] != first["run_id"]
    assert len(discover_events(tmp_path, "insurance")) == 5
    root = Path(first["run_root"])
    (root / "event_assets.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_event(root, tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        publish_event(inputs(), settings, provenance, tmp_path)


def test_300_snapshot_and_failed_run_does_not_publish(tmp_path):
    provenance = {"physical_run_id": "p", "insurance_run_id": "i"}
    result = publish_event(inputs(), EventSettings(year=2026, return_period=300), provenance, tmp_path, curves())
    metadata, _ = load_event(Path(result["run_root"]), tmp_path)
    assert "fragility_snapshot.parquet" in metadata["artifacts"]
    with pytest.raises(ValueError):
        publish_event(inputs(), EventSettings(year=2027), provenance, tmp_path)
    assert len(discover_events(tmp_path, "i")) == 1
    assert not list(tmp_path.glob("**/*.tmp"))


def test_map_metric_coordinates_and_escaped_asset():
    rows = calculate_event(inputs(), EventSettings(year=2026, states=("TX",)))
    frame = rows.filter(pl.col("scenario_id") == "BASELINE_CURRENT").to_pandas()
    frame.loc[0, "asset_id"] = "<script>asset</script>"
    figure, omitted = build_event_map(frame, "gross_event_damage_usd")
    assert omitted == 0
    html = figure.get_root().render()
    assert "&lt;script&gt;" in html and "Unaffected" in html
    frame.loc[0, "latitude"] = None
    assert build_event_map(frame, "insured_event_payout_usd")[1] == 1
    frame["latitude"] = np.nan
    assert build_event_map(frame, "insured_event_payout_usd") == (None, 2)


def _page():
    from cadence.ui.insurance_event_page import render_event
    render_event("/unused", {"run_id": "insurance", "year_start": 2026, "year_end": 2027})


def test_event_ui_explicit_run_stale_inputs_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(insurance_event_page, "EVENT_ROOT", tmp_path)
    monkeypatch.setattr(insurance_event_page, "render_event_map", lambda *args: None)
    calls = []
    def run(_, settings):
        calls.append(settings)
        return publish_event(inputs().with_columns(pl.lit(settings.year).alias("year")), settings,
                             {"physical_run_id": "physical", "insurance_run_id": "insurance"}, tmp_path)
    monkeypatch.setattr(insurance_event_page, "run_event", run)
    app = AppTest.from_function(_page).run()
    assert not app.exception and not calls
    assert app.selectbox[1].value == 2026 and app.selectbox[2].value == 100
    app.button[0].click().run()
    assert not app.exception and len(calls) == 1
    assert [item.value for item in app.metric[:2]] == ["$80,000", "$60,000"]
    assert app.selectbox[-1].value == "BASELINE_CURRENT"
    app.selectbox[2].set_value(200).run()
    assert not app.exception and len(calls) == 1 and not app.metric
    assert any("inputs changed" in item.value for item in app.info)
    saved_id = discover_events(tmp_path, "insurance")[0]["run_id"]
    app.selectbox[0].set_value(saved_id).run()
    assert not app.exception and len(calls) == 1 and app.metric
    app.selectbox[0].set_value(None).run()
    app.selectbox[2].set_value(200).run()
    app.radio[0].set_value("Selected states").run()
    assert app.button[0].disabled
    app.multiselect[0].set_value(["TX"]).run()
    app.button[0].click().run()
    assert not app.exception and len(calls) == 2
    assert app.metric[0].value == "$50,000"
    metadata = json.loads(next(path for path in tmp_path.glob("**/run_metadata.json")
                               if json.loads(path.read_text())["settings"]["states"] == ["TX"]).read_text())
    assert metadata["settings"]["return_period"] == 200


def test_event_input_loading_preserves_sources_and_allows_missing_coordinates(tmp_path, monkeypatch):
    from cadence.ui import insurance_event_data as data

    physical = tmp_path / "physical/schema_version=v0.4.0/run_id=physical"
    insurance = tmp_path / "insurance"
    insurance.mkdir()
    damage_dir = physical / "annual_scenario_damage/year=2026"
    cost_dir = physical / "annual_alternative_analysis/year=2026"
    damage_dir.mkdir(parents=True)
    cost_dir.mkdir(parents=True)
    source = inputs()
    policy_columns = ["asset_id", "policy_id", "insured_value", "deductible_amount",
                      "deductible_type", "peril", "current_premium"]
    source.select(policy_columns).unique().write_parquet(insurance / "policy_snapshot.parquet")
    source.drop(policy_columns[1:] + ["active_installed_capex_usd", "latitude"]).write_parquet(damage_dir / "part.parquet")
    source.select("asset_id", "year", "scenario_id", "active_installed_capex_usd").write_parquet(cost_dir / "part.parquet")
    physical_metadata = {"run_id": "physical", "annual_damage_path": str(damage_dir.parent),
                         "annual_analysis_path": str(cost_dir.parent)}
    insurance_metadata = {"run_id": "insurance", "physical_run_id": "physical", "year_start": 2026,
                          "year_end": 2026, "policy_checksum": "policy"}
    (physical / "run_metadata.json").write_text(json.dumps(physical_metadata))
    (insurance / "run_metadata.json").write_text(json.dumps(insurance_metadata))
    monkeypatch.setattr(data, "ALTERNATIVE_RESULTS_ROOT", tmp_path / "physical")
    monkeypatch.setattr(data, "EVENT_ROOT", tmp_path / "events")
    monkeypatch.setattr(data, "load_insurance_metadata", lambda _: insurance_metadata)
    monkeypatch.setattr(data, "load_run_metadata", lambda _: physical_metadata)
    monkeypatch.setattr(data, "load_fragility_results", lambda *_: curves().to_pandas())
    before = {path: path.read_bytes() for root in (physical, insurance) for path in root.rglob("*") if path.is_file()}
    for period in (100, 200, 300, 500):
        run = data.run_event(str(insurance), EventSettings(year=2026, return_period=period, states=("TX",)))
        _, rows = load_event(Path(run["run_root"]), data.EVENT_ROOT)
        assert rows.height == 8
        assert rows["latitude"].null_count() == 8
        assert summarize_event(rows)["gross_event_damage_usd"].null_count() == 0
    assert before == {path: path.read_bytes() for path in before}
    with pytest.raises(ValueError, match="horizon"):
        data.run_event(str(insurance), EventSettings(year=2027))
    damaged = pl.read_parquet(damage_dir / "part.parquet").drop("state_code")
    damaged.write_parquet(damage_dir / "part.parquet")
    with pytest.raises(ValueError, match="unknown asset states"):
        data.run_event(str(insurance), EventSettings(year=2026, states=("TX",)))
    run = data.run_event(str(insurance), EventSettings(year=2026))
    assert load_event(Path(run["run_root"]), data.EVENT_ROOT)[1]["gross_event_damage_usd"].null_count() == 0


def test_event_ui_failure_does_not_display_previous_success(tmp_path, monkeypatch):
    monkeypatch.setattr(insurance_event_page, "EVENT_ROOT", tmp_path)
    monkeypatch.setattr(insurance_event_page, "render_event_map", lambda *args: None)
    def run(_, settings):
        if settings.return_period == 500:
            raise ValueError("missing event input")
        return publish_event(inputs(), settings, {"physical_run_id": "physical", "insurance_run_id": "insurance"}, tmp_path)
    monkeypatch.setattr(insurance_event_page, "run_event", run)
    app = AppTest.from_function(_page).run()
    app.button[0].click().run()
    assert app.metric
    app.selectbox[2].set_value(500).run()
    app.button[0].click().run()
    assert not app.exception and not app.metric
    assert "missing event input" in app.error[0].value
