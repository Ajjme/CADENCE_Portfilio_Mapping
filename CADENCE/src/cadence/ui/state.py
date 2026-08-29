"""Session-state keys and deterministic invalidation rules."""

from collections.abc import MutableMapping
from typing import Any

SOURCE_KEYS = (
    "portfolio_frame",
    "portfolio_validation",
    "selected_asset_ids",
    "analysis_identity",
    "derived_workbook_path",
    "run_state",
)
ANALYSIS_KEYS = ("analysis_identity", "derived_workbook_path", "run_state")


def update_source_identity(state: MutableMapping[str, Any], checksum: str) -> bool:
    """Set the source checksum and clear dependent state when it changes."""
    if state.get("portfolio_checksum") == checksum:
        return False
    for key in SOURCE_KEYS:
        state.pop(key, None)
    state["portfolio_checksum"] = checksum
    return True


def update_analysis_identity(state: MutableMapping[str, Any], identity: str) -> bool:
    """Clear run state when the filtered portfolio identity changes."""
    if state.get("analysis_identity") == identity:
        return False
    for key in ANALYSIS_KEYS:
        state.pop(key, None)
    state["analysis_identity"] = identity
    return True