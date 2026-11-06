import pandas as pd
from streamlit.testing.v1 import AppTest

from cadence.ui.pages import results


def _study_page() -> None:
    from cadence.ui.pages.results import _render_market_study

    _render_market_study("/tmp/alternative/run_id=parent", "__PORTFOLIO__")


def test_study_tab_reads_published_rows_without_running_engine(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(results, "run_market_study", lambda *_: calls.append("run"))
    monkeypatch.setattr(results, "find_study", lambda *_: "/tmp/study")
    monkeypatch.setattr(results, "load_study", lambda *_: (
        {"run_id": "study", "policy_id": "annual_v2", "last_verified_year": 2026, "evaluation_end_year": 2046,
         "run_config": {"enabled_cost_streams": ["material", "labor"], "real_discount_rate": 0.02}},
        pd.DataFrame([{"year": 2026, "material_id": "OFFICIAL_ASPHALT", "asset_count": 2,
                       "portfolio_count": 2, "share_percent": 100.0}]),
        pd.DataFrame([{"year": 2026, "repair_usd": 2.0, "loss_of_use_usd": 0.0,
                       "material_usd": 0.0, "labor_usd": 0.0, "disposal_usd": 0.0,
                       "carbon_usd": 0.0, "unknown_count": 0, "replacement_count": 0,
                       "eul_replacements": 0, "damage_replacements": 0, "economic_replacements": 0}]),
    ))
    monkeypatch.setattr(results, "load_decisions", lambda *_: pd.DataFrame({"asset_id": ["A"]}))
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/alternative/run_id=parent", "run_id": "parent"}
    app.run()

    assert not app.exception
    assert [button.label for button in app.button] == ["Run Market Study"]
    assert calls == []
    assert any("Run study" in item.value for item in app.caption)
    assert app.number_input[0].value == 10
    assert app.number_input[0].disabled


def test_study_tab_requires_matching_active_run() -> None:
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/other", "run_id": "other"}
    app.run()

    assert not app.exception
    assert not app.button
    assert any("matching active session" in item.value for item in app.info)


def test_limit_changes_do_not_run_until_explicit_click(monkeypatch):
    calls, lookups = [], []
    def find(*args):
        lookups.append(args[-1])
        return None
    def run(*args):
        calls.append(args[-1])
        return {"run_id": "new", "cache_hit": False}
    monkeypatch.setattr(results, "find_study", find)
    monkeypatch.setattr(results, "run_market_study", run)
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/alternative/run_id=parent", "run_id": "parent"}
    app.run()
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert not app.number_input[0].disabled
    assert calls == []
    assert lookups[-1] == 10
    app.number_input[0].set_value(5).run()
    assert calls == []
    assert lookups[-1] == 5
    app.button[0].click().run()
    assert calls == [5]
    assert not app.exception
    app.toggle[0].set_value(False).run()
    assert lookups[-1] is None


def test_calculation_errors_are_visible(monkeypatch):
    monkeypatch.setattr(results, "find_study", lambda *_: None)
    def fail(*_):
        raise ValueError("Missing verified prices")
    monkeypatch.setattr(results, "run_market_study", fail)
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/alternative/run_id=parent", "run_id": "parent"}
    app.run().button[0].click().run()
    assert not app.exception
    assert any("Missing verified prices" in item.value for item in app.error)