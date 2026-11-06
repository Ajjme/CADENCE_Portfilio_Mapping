"""Read a published study without running the market simulation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.economics.market_pipeline import (
    POLICY_ID, SCHEMA_VERSION, STUDY_ROOT, study_identity, study_path, verify_artifacts,
)


def find_study(run_root: str, run_state: object, max_payback_years: int | None = None) -> str | None:
    """Find the exact saved study for this session's parent and input snapshots."""
    if not isinstance(run_state, dict) or Path(str(run_state.get("run_root", ""))).resolve() != Path(run_root).resolve():
        return None
    asset = Path(str(run_state.get("economics_ready_asset_path", ""))).resolve()
    damage = Path(str(run_state.get("asset_damage_result_path", ""))).resolve()
    if not asset.is_file() or not damage.is_file():
        return None
    identity = study_identity(run_root, run_state, max_payback_years)
    root = study_path(identity)
    manifest_path = root / "run_metadata.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("identity") != identity:
        raise ValueError("Saved Market Study settings or sources do not match")
    return str(root.resolve())


@st.cache_data(show_spinner=False)
def load_study(study_root: str, parent_root: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Read verified aggregates without loading the portfolio's candidate ledger."""
    root = Path(study_root).resolve()
    if not root.is_relative_to(STUDY_ROOT.resolve()):
        raise ValueError("Study is outside the configured results root")
    manifest = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("policy_id") != POLICY_ID
            or root.name != f"run_id={manifest.get('run_id')}"
            or manifest.get("parent_run_root") != str(Path(parent_root).resolve())):
        raise ValueError("Market Study identity does not match the selected Alternative run")
    verify_artifacts(root, manifest)
    stock = pd.read_parquet(root / "annual_roof_share.parquet")
    costs = pd.read_parquet(root / "annual_portfolio_costs.parquet")
    if (stock.groupby("year")["asset_count"].sum() != manifest["asset_count"]).any():
        raise ValueError("Market Study roof counts do not match the parent portfolio")
    return manifest, stock, costs


@st.cache_data(show_spinner=False)
def load_decisions(study_root: str, parent_root: str, year: int, asset_id: str | None = None) -> pd.DataFrame:
    load_study(study_root, parent_root)
    filters = [("year", "==", year)]
    if asset_id is not None:
        filters.append(("asset_id", "==", asset_id))
    return pd.read_parquet(Path(study_root) / "replacement_decisions.parquet", filters=filters)


@st.cache_data(show_spinner=False)
def load_candidate_audit(study_root: str, parent_root: str, year: int, asset_id: str) -> pd.DataFrame:
    load_study(study_root, parent_root)
    return pd.read_parquet(
        Path(study_root) / "candidate_cash_flows.parquet",
        filters=[("decision_year", "==", year), ("asset_id", "==", asset_id)],
    )