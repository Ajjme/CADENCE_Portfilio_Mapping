"""Publish immutable, scenario-specific annual market decisions."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import polars as pl

from cadence.economics.market_inputs import file_sha256, load_study_inputs, study_source_identity
from cadence.economics.market_study import (
    COMPONENTS, EXTENSION_POLICY, MATERIALS, POLICY_ID, TIMING_POLICY,
    AssetStudyInput, simulate_assets, validate_payback_limit,
)
from cadence.reference_data.year1_damage import _fragility_identity
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, FRAGILITY_ROOT, RESULTS_ROOT

SCHEMA_VERSION = "v0.2.0"
STUDY_ROOT = RESULTS_ROOT / "roof_market_study"
BATCH_SIZE = 100


def study_fragility_identity(root: Path) -> str:
    baseline = pl.read_parquet(
        str(root / "annual_scenario_damage/year=*/*.parquet"),
        columns=["climate_zone"], hive_partitioning=False,
    ).select("climate_zone").unique()
    keys = baseline.join(pl.DataFrame({"lookup_roof_age": list(range(1, 31))}), how="cross")
    return _fragility_identity(keys, FRAGILITY_ROOT)


def study_identity(run_root: str, run_state: dict, max_payback_years: int | None = None) -> dict:
    """Resolve exactly the same identity for running and reopening a scenario."""
    limit = validate_payback_limit(max_payback_years)
    root = Path(run_root).resolve()
    if not root.is_relative_to(ALTERNATIVE_RESULTS_ROOT.resolve()):
        raise ValueError("Selected Alternative run is outside the results root")
    if not isinstance(run_state, dict) or Path(str(run_state.get("run_root", ""))).resolve() != root:
        raise ValueError("Market Study requires the matching active session run")
    source = root / "run_metadata.json"
    metadata = json.loads(source.read_text(encoding="utf-8"))
    if metadata.get("run_id") != run_state.get("run_id") or root.name != f"run_id={metadata['run_id']}":
        raise ValueError("The active run does not match the selected Alternative run")
    return {
        "parent_run_id": metadata["run_id"], "parent_run_root": str(root),
        "parent_metadata_sha256": file_sha256(source),
        "economics_assets_sha256": file_sha256(Path(run_state["economics_ready_asset_path"])),
        "asset_damage_sha256": file_sha256(Path(run_state["asset_damage_result_path"])),
        "study_fragility_identity": study_fragility_identity(root),
        "sources": study_source_identity(root, metadata),
        "policy_id": POLICY_ID, "schema_version": SCHEMA_VERSION,
        "max_payback_years": limit, "extension_policy": EXTENSION_POLICY,
        "timing_policy": TIMING_POLICY, "horizon_policy": "max_initial_and_new_service_lives_and_limit",
        "terminal_value_policy": "straight_line_npv_only",
    }


def study_path(identity: dict) -> Path:
    study_id = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]
    return STUDY_ROOT / f"schema_version={SCHEMA_VERSION}" / f"run_id={study_id}"


def verify_artifacts(root: Path, manifest: dict) -> None:
    expected = manifest.get("artifact_checksums")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Market Study artifact checksums are missing")
    actual_paths = {str(path.relative_to(root)) for path in root.rglob("*.parquet") if path.is_file()}
    if actual_paths != set(expected):
        raise ValueError("Market Study artifact inventory is incomplete or changed")
    for name, checksum in expected.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_sha256(path) != checksum:
            raise ValueError(f"Market Study artifact checksum mismatch: {name}")


def run_market_study(run_root: str, run_state: dict, max_payback_years: int | None = None) -> dict:
    """Recalculate stock, not just displayed eligibility, when acceptance changes."""
    identity = study_identity(run_root, run_state, max_payback_years)
    root = Path(run_root).resolve()
    metadata = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    target = study_path(identity)
    manifest_path = target / "run_metadata.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("identity") != identity:
            raise ValueError("Market Study cache identity mismatch")
        verify_artifacts(target, manifest)
        return {**manifest, "cache_hit": True, "run_root": str(target)}
    if target.exists():
        raise ValueError("Market Study output is incomplete; refusing to overwrite it")
    config = metadata["run_config"]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}-{uuid4().hex}.tmp"
    try:
        temporary.mkdir()
        assets, prices, removals, lives, risk = load_study_inputs(
            root, Path(run_state["economics_ready_asset_path"]), metadata,
            Path(run_state["asset_damage_result_path"]), temporary / "inputs",
        )
        if assets.height == 0 or assets.height != int(metadata["asset_count"]):
            raise ValueError("Saved study asset count differs from Alternative run")
        for name in ("annual_asset_stock.parquet", "replacement_decisions.parquet", "candidate_cash_flows.parquet"):
            (temporary / name).mkdir()
        stock_parts, total_parts = [], []
        ledger_part = 0

        def save_audit(frame: pd.DataFrame) -> None:
            nonlocal ledger_part
            frame.to_parquet(temporary / "candidate_cash_flows.parquet" / f"part-{ledger_part:06d}.parquet", index=False)
            ledger_part += 1

        for batch_number, batch in enumerate(assets.iter_slices(BATCH_SIZE)):
            inputs = []
            for asset in batch.iter_rows(named=True):
                asset_id = str(asset["asset_id"])
                inputs.append(AssetStudyInput(
                    asset_id, asset["official_current_material_id"], int(asset["input_roof_age"]),
                    lives[asset_id]["initial_eul"], {m: lives[asset_id][m] for m in MATERIALS},
                    prices[asset_id], removals[asset_id],
                    lambda year, material, age, identifier=asset_id: risk(identifier, year, material, age),
                ))
            annual, decisions = simulate_assets(
                inputs, int(config["start_year"]), int(config["end_year"]),
                float(config["real_discount_rate"]), max_payback_years, save_audit,
            )
            annual["total_usd"] = annual[list(COMPONENTS)].sum(axis=1, min_count=len(COMPONENTS))
            annual["unresolved_reason"] = annual["unresolved_reason"].astype("string")
            annual.to_parquet(temporary / "annual_asset_stock.parquet" / f"part-{batch_number:06d}.parquet", index=False)
            # Stable nullable types are needed across all-valid and all-unknown batches.
            for column in ("max_payback_years",):
                decisions[column] = decisions[column].astype("Int64")
            for column in ("unresolved_reason",):
                decisions[column] = decisions[column].astype("string")
            decisions.to_parquet(temporary / "replacement_decisions.parquet" / f"part-{batch_number:06d}.parquet", index=False)
            stock_parts.append(annual.groupby(["year", "material_id"]).size().rename("asset_count").reset_index())
            for cause, name in (("EUL", "eul_replacements"), ("damage", "damage_replacements"),
                                ("economic", "economic_replacements")):
                annual[name] = (annual["replacement_cause"] == cause).astype(int)
            annual["replacement_count"] = annual["replacement_event"].astype(int)
            annual["unknown_count"] = (annual["material_id"] == "UNKNOWN").astype(int)
            columns = [*COMPONENTS, "total_usd", "replacement_count", "eul_replacements",
                       "damage_replacements", "economic_replacements", "unknown_count"]
            total_parts.append(annual.groupby("year")[columns].agg(lambda values: values.sum(min_count=len(values))))
        stock = pd.concat(stock_parts).groupby(["year", "material_id"], as_index=False)["asset_count"].sum()
        stock["portfolio_count"] = assets.height
        stock["share_percent"] = 100 * stock["asset_count"] / assets.height
        totals = pd.concat(total_parts).groupby("year").agg(
            lambda values: values.sum(min_count=len(values)),
        ).reset_index()
        stock.to_parquet(temporary / "annual_roof_share.parquet", index=False)
        totals.to_parquet(temporary / "annual_portfolio_costs.parquet", index=False)
        max_duration = max(max(values.values()) for values in lives.values())
        max_duration = max(max_duration, max_payback_years or 0)
        manifest = {
            "run_id": target.name.removeprefix("run_id="), "schema_version": SCHEMA_VERSION,
            "policy_id": POLICY_ID, "parent_run_id": metadata["run_id"], "parent_run_root": str(root),
            "run_config": config, "temporary_tile_policy": metadata.get("temporary_tile_policy"),
            "asset_count": assets.height, "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "identity": identity, "max_payback_years": max_payback_years,
            "last_verified_year": int(config["end_year"]),
            "evaluation_end_year": int(config["end_year"]) + max_duration,
            "maximum_evaluation_years": max_duration,
            "perspective": "enabled_study_costs_pre_insurance_economic_acceptance_proxy",
            "artifact_checksums": {
                str(path.relative_to(temporary)): file_sha256(path)
                for path in sorted(temporary.rglob("*.parquet")) if path.is_file()
            },
        }
        if study_identity(run_root, run_state, max_payback_years) != identity:
            raise ValueError("Market Study inputs changed during calculation; rerun with stable inputs")
        (temporary / "run_metadata.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8",
        )
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {**manifest, "cache_hit": False, "run_root": str(target)}
