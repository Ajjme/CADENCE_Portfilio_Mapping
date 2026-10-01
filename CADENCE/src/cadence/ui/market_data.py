"""Read a published study without running the market simulation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.economics.market_pipeline import SCHEMA_VERSION, STUDY_ROOT


def find_study(run_root: str, run_state: object) -> str | None:
    """Find the exact saved study for this session's parent and input snapshots."""
    if not isinstance(run_state, dict) or Path(str(run_state.get("run_root", ""))).resolve() != Path(run_root).resolve():
        return None
    asset = Path(str(run_state.get("economics_ready_asset_path", ""))).resolve()
    damage = Path(str(run_state.get("asset_damage_result_path", ""))).resolve()
    if not asset.is_file() or not damage.is_file():
        return None
    asset_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
    damage_hash = hashlib.sha256(damage.read_bytes()).hexdigest()
    matches = []
    for path in (STUDY_ROOT / f"schema_version={SCHEMA_VERSION}").glob("run_id=*/run_metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        identity = metadata.get("identity", {})
        if (metadata.get("parent_run_root") == str(Path(run_root).resolve())
                and metadata.get("parent_run_id") == run_state.get("run_id")
                and identity.get("economics_assets_sha256") == asset_hash
                and identity.get("asset_damage_sha256") == damage_hash):
            matches.append(str(path.parent.resolve()))
    if len(matches) > 1:
        raise ValueError("Multiple studies match this run; select a specific study ID")
    return matches[0] if matches else None


@st.cache_data(show_spinner=False)
def load_study(study_root: str, parent_root: str) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read four immutable study artifacts with their parent identity."""
    root = Path(study_root).resolve()
    if not root.is_relative_to(STUDY_ROOT.resolve()):
        raise ValueError("Study is outside the configured results root")
    manifest = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != SCHEMA_VERSION
            or root.name != f"run_id={manifest.get('run_id')}"
            or manifest.get("parent_run_root") != str(Path(parent_root).resolve())):
        raise ValueError("Market Study identity does not match the selected Alternative run")
    stock = pd.read_parquet(root / "annual_roof_share.parquet")
    costs = pd.read_parquet(root / "annual_portfolio_costs.parquet")
    decisions = pd.read_parquet(root / "replacement_decisions.parquet")
    if (stock.groupby("year")["asset_count"].sum() != manifest["asset_count"]).any():
        raise ValueError("Market Study roof counts do not match the parent portfolio")
    return manifest, stock, costs, decisions