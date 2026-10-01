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
        {"run_id": "study", "run_config": {"enabled_cost_streams": ["material", "labor"]}},
        pd.DataFrame([{"year": 2026, "material_id": "OFFICIAL_ASPHALT", "asset_count": 2,
                       "portfolio_count": 2, "share_percent": 100.0}]),
        pd.DataFrame([{"year": 2026, "repair_usd": 2.0, "loss_of_use_usd": 0.0,
                       "material_usd": 0.0, "labor_usd": 0.0, "disposal_usd": 0.0,
                       "carbon_usd": 0.0, "unknown_count": 0, "replacement_count": 0,
                       "eul_replacements": 0, "damage_replacements": 0}]),
        pd.DataFrame(),
    ))
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/alternative/run_id=parent", "run_id": "parent"}
    app.run()

    assert not app.exception
    assert [button.label for button in app.button] == ["Run Market Study"]
    assert calls == []
    assert any("Run study" in item.value for item in app.caption)


def test_study_tab_requires_matching_active_run() -> None:
    app = AppTest.from_function(_study_page)
    app.session_state["run_state"] = {"run_root": "/tmp/other", "run_id": "other"}
    app.run()

    assert not app.exception
    assert not app.button
    assert any("matching active session" in item.value for item in app.info)