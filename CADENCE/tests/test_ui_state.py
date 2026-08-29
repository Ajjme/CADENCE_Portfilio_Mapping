from cadence.ui.state import update_analysis_identity, update_source_identity


def test_source_change_invalidates_portfolio_and_run_state() -> None:
    state = {
        "portfolio_checksum": "old",
        "portfolio_frame": object(),
        "selected_asset_ids": ["A-1"],
        "analysis_identity": "old-selection",
        "derived_workbook_path": "selected.xlsx",
        "run_state": {"run_id": "old-run"},
    }

    assert update_source_identity(state, "new") is True
    assert state == {"portfolio_checksum": "new"}
    assert update_source_identity(state, "new") is False


def test_filter_change_invalidates_only_analysis_state() -> None:
    state = {
        "portfolio_checksum": "source",
        "analysis_identity": "old-selection",
        "derived_workbook_path": "selected.xlsx",
        "run_state": {"run_id": "old-run"},
    }

    assert update_analysis_identity(state, "new-selection") is True
    assert state == {
        "portfolio_checksum": "source",
        "analysis_identity": "new-selection",
    }