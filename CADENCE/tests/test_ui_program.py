import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from cadence.program.analysis import evaluate
from cadence.ui import program_page as program
from cadence.ui.program_charts import funding_figure, funding_waterfall
from test_program_analysis import inputs


def _page():
    from cadence.ui import program_page as program
    program.render()


@pytest.fixture
def page_data(inputs, monkeypatch):
    candidates, annual = evaluate(inputs)
    metadata = {
        "run_id": "programfixture", "asset_id": "A", "parent_run_id": "physical",
        "run_config": inputs.config.model_dump(mode="json"), "temporary_tile_policy": None,
    }
    monkeypatch.setattr(program, "discover_runs", lambda _: [])
    monkeypatch.setattr(program, "discover_program_runs", lambda: [
        {"run_id": "programfixture", "run_root": "/unused"},
    ])
    monkeypatch.setattr(program, "load_program_results", lambda _: (
        metadata, candidates.to_pandas(), annual.to_pandas(),
    ))
    return metadata, candidates.to_pandas(), annual.to_pandas()


def test_empty_page_and_public_good_buttons(monkeypatch):
    monkeypatch.setattr(program, "discover_runs", lambda _: [])
    monkeypatch.setattr(program, "discover_program_runs", lambda: [])
    app = AppTest.from_function(_page).run()
    assert not app.exception
    assert any("No saved Program" in item.value for item in app.info)
    app.button[0].click().run()
    assert not app.exception
    assert any("Not yet modeled" in item.value for item in app.info)
    assert not app.selectbox


def test_saved_page_selection_and_independent_manual_year(page_data):
    app = AppTest.from_function(_page).run()
    assert not app.exception
    assert app.selectbox[0].value is None
    app.selectbox[0].set_value("programfixture").run()
    assert not app.exception
    assert [widget.label for widget in app.selectbox] == [
        "Program run", "Target roof", "Counterfactual", "Installation year",
    ]
    app.selectbox[1].set_value("NEW_METAL").run()
    app.selectbox[2].set_value("CONVENTIONAL_AT_YEAR").run()
    app.selectbox[3].set_value(2028).run()
    assert not app.exception
    assert any("Selected-year grant" in item.value for item in app.markdown)
    table = app.dataframe[0].value.copy()
    assert len(table) == 6
    app.button[1].click().run()
    assert not app.exception
    pd.testing.assert_frame_equal(table, app.dataframe[0].value)
    assert app.selectbox[3].value == 2028
    assert len(app.get("download_button")) == 2


def test_creation_selects_persisted_result_and_handles_errors(page_data, monkeypatch):
    monkeypatch.setattr(program, "discover_runs", lambda _: [
        {"run_id": "physical", "run_root": "/physical"},
    ])
    monkeypatch.setattr(program, "load_run_metadata", lambda _: {})
    monkeypatch.setattr(program, "load_summary", lambda _: pd.DataFrame({"asset_id": ["A"]}))
    calls = []

    def create(root, asset):
        calls.append((root, asset))
        return {"run_id": "programfixture", "run_root": "/unused", "cache_hit": False}

    monkeypatch.setattr(program, "create_program_run", create)
    app = AppTest.from_function(_page).run()
    app.selectbox[0].set_value("physical").run()
    app.button[0].click().run()
    assert not app.exception
    assert calls == [("/physical", "A")]
    assert app.selectbox[2].value == "programfixture"
    assert any("results saved" in item.value for item in app.success)

    def invalid(*_):
        raise ValueError("Missing fragility snapshot; rerun Alternative Analysis")

    monkeypatch.setattr(program, "create_program_run", invalid)
    app.button[0].click().run()
    assert not app.exception
    assert any("rerun Alternative" in item.value for item in app.error)


def test_corrupt_saved_run_is_an_explicit_error(page_data, monkeypatch):
    def corrupt(_):
        raise ValueError("Program artifact is missing or corrupt")

    monkeypatch.setattr(program, "load_program_results", corrupt)
    app = AppTest.from_function(_page).run()
    app.selectbox[0].set_value("programfixture").run()
    assert not app.exception
    assert "corrupt" in app.error[0].value


def test_chart_and_waterfall_values_match_export(page_data):
    _, candidates, _ = page_data
    frame = candidates.loc[
        (candidates["target_scenario"] == "NEW_METAL") & (candidates["counterfactual"] == "KEEP_TO_EOL")
    ]
    chart = funding_figure(frame, 2028)
    assert list(chart.data[0].y) == frame["economic_grant_usd"].tolist()
    assert list(chart.data[1].y) == frame["upfront_gap_usd"].tolist()
    assert chart.layout.shapes[0].x0 == 2028
    row = frame.iloc[0]
    waterfall = funding_waterfall(row)
    values = waterfall.data[0].y
    assert sum(values[:5]) == pytest.approx(row["npv_at_installation_usd"])
    assert sum(values[:5]) + values[6] == pytest.approx(row["grant_adjusted_npv_usd"])
    csv = frame.to_csv(index=False)
    assert "economic_grant_usd" in csv
    assert str(row["economic_grant_usd"]) in csv
