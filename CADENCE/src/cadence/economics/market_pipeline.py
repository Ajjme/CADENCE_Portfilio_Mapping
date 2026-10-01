"""Publish an immutable roof-stock study linked to an Alternative run."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import polars as pl

from cadence.economics.market_inputs import load_study_inputs
from cadence.economics.market_study import COMPONENTS, simulate_asset
from cadence.reference_data.year1_damage import _fragility_identity
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, FRAGILITY_ROOT, RESULTS_ROOT

SCHEMA_VERSION = "v0.1.0"
POLICY_ID = "annual_eul_damage_removal_straight_line_recursive_v1"
STUDY_ROOT = RESULTS_ROOT / "roof_market_study"


def study_fragility_identity(root: Path) -> str:
    """Track every reachable lookup age, not just the parent's four scenario paths."""
    baseline = pl.read_parquet(
        str(root / "annual_scenario_damage/year=*/*.parquet"),
        columns=["climate_zone"], hive_partitioning=False,
    ).select("climate_zone").unique()
    keys = baseline.join(pl.DataFrame({"lookup_roof_age": list(range(1, 31))}), how="cross")
    return _fragility_identity(keys, FRAGILITY_ROOT)


def run_market_study(run_root: str, run_state: dict) -> dict:
    """Compute only on a cache miss; retain source and decision provenance."""
    root = Path(run_root).resolve()
    if not root.is_relative_to(ALTERNATIVE_RESULTS_ROOT.resolve()):
        raise ValueError("Selected Alternative run is outside the results root")
    if not isinstance(run_state, dict) or Path(str(run_state.get("run_root", ""))).resolve() != root:
        raise ValueError("Market Study requires the matching active session run")
    source = root / "run_metadata.json"
    if not source.is_file():
        raise ValueError("Alternative run metadata is missing")
    metadata = json.loads(source.read_text(encoding="utf-8"))
    if metadata.get("run_id") != run_state.get("run_id") or root.name != f"run_id={metadata['run_id']}":
        raise ValueError("The active run does not match the selected Alternative run")
    assets_path = Path(str(run_state.get("economics_ready_asset_path", ""))).resolve()
    damage_path = Path(str(run_state.get("asset_damage_result_path", ""))).resolve()
    if not assets_path.is_file() or not damage_path.is_file():
        raise ValueError("The active run needs its saved asset and hazard inputs")
    asset_hash = hashlib.sha256(assets_path.read_bytes()).hexdigest()
    damage_hash = hashlib.sha256(damage_path.read_bytes()).hexdigest()
    identity = json.dumps({
        "parent_run_id": metadata["run_id"], "parent_metadata_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "economics_assets_sha256": asset_hash, "asset_damage_sha256": damage_hash,
        "study_fragility_identity": study_fragility_identity(root),
        "policy_id": POLICY_ID, "schema_version": SCHEMA_VERSION,
    }, sort_keys=True)
    study_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    target = STUDY_ROOT / f"schema_version={SCHEMA_VERSION}" / f"run_id={study_id}"
    manifest_path = target / "run_metadata.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("identity") != json.loads(identity):
            raise ValueError("Market Study cache identity mismatch")
        return {**manifest, "cache_hit": True, "run_root": str(target)}
    if target.exists():
        raise ValueError("Market Study output is incomplete; refusing to overwrite it")

    assets, prices, removals, lives, risk = load_study_inputs(root, assets_path, metadata, damage_path)
    if assets.height != int(metadata["asset_count"]):
        raise ValueError("Saved study asset count differs from Alternative run")
    config = metadata["run_config"]
    frames = []
    audits = []
    for asset in assets.iter_rows(named=True):
        asset_id = str(asset["asset_id"])
        rows, decisions = simulate_asset(
            asset_id, asset["official_current_material_id"], int(asset["input_roof_age"]),
            lives[asset_id]["initial_eul"], {material: lives[asset_id][material] for material in lives[asset_id] if material != "initial_eul"},
            int(config["start_year"]), int(config["end_year"]), float(config["real_discount_rate"]),
            prices[asset_id], removals[asset_id],
            lambda year, material, age, identifier=asset_id: risk(identifier, year, material, age),
        )
        frames.append(rows)
        if not decisions.empty:
            audits.append(decisions)
    annual = pd.concat(frames, ignore_index=True)
    annual["total_usd"] = annual[list(COMPONENTS)].sum(axis=1, min_count=len(COMPONENTS))
    decisions = pd.concat(audits, ignore_index=True) if audits else pd.DataFrame(
        columns=["asset_id", "year", "cause", "old_material_id", "candidate_material_id", "selected",
                 "trigger_usd", "roof_value_usd", "incremental_npv_usd"]
    )
    stock = annual.groupby(["year", "material_id"], dropna=False).size().rename("asset_count").reset_index()
    stock["portfolio_count"] = assets.height
    stock["share_percent"] = 100 * stock["asset_count"] / assets.height
    totals = annual.groupby("year")[list(COMPONENTS) + ["total_usd"]].agg(
        lambda values: values.sum(min_count=len(values))
    ).reset_index()
    totals["replacement_count"] = annual.groupby("year")["replacement_event"].sum().to_numpy()
    totals["eul_replacements"] = annual.groupby("year")["replacement_cause"].apply(
        lambda causes: int((causes == "EUL").sum())
    ).to_numpy()
    totals["damage_replacements"] = annual.groupby("year")["replacement_cause"].apply(
        lambda causes: int((causes == "damage").sum())
    ).to_numpy()
    totals["unknown_count"] = annual.groupby("year")["material_id"].apply(lambda values: int((values == "UNKNOWN").sum())).to_numpy()
    manifest = {
        "run_id": study_id, "schema_version": SCHEMA_VERSION, "policy_id": POLICY_ID,
        "parent_run_id": metadata["run_id"], "parent_run_root": str(root),
        "run_config": config, "temporary_tile_policy": metadata.get("temporary_tile_policy"),
        "asset_count": assets.height, "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "identity": json.loads(identity),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}-{uuid4().hex}.tmp"
    try:
        temporary.mkdir()
        annual.to_parquet(temporary / "annual_asset_stock.parquet", index=False)
        decisions.to_parquet(temporary / "replacement_decisions.parquet", index=False)
        stock.to_parquet(temporary / "annual_roof_share.parquet", index=False)
        totals.to_parquet(temporary / "annual_portfolio_costs.parquet", index=False)
        (temporary / "run_metadata.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {**manifest, "cache_hit": False, "run_root": str(target)}