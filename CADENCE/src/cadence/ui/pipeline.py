"""Thin orchestration over existing CADENCE pipeline entry points."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from cadence.economics.alternative_pipeline import run_alternative_analysis_pipeline
from cadence.economics.contracts import EconomicsRunConfig
from cadence.insurance.pipeline import publish_insurance
from cadence.reference_data.economics_assets import build_economics_asset_features
from cadence.reference_data.year1_damage import build_asset_scoped_damage
from cadence.ui.paths import (
    ALTERNATIVE_RESULTS_ROOT,
    CADENCE_ROOT,
    CLIMATE_DELTA,
    CLIMATE_ZONES,
    ECONOMICS_CONFIG,
    FRAGILITY_ROOT,
    RESULTS_ROOT,
    WIND_RETURN_PERIODS,
)
from cadence.ui.workbooks import sha256_file, validate_portfolio

ProgressCallback = Callable[[str, str], None]


def load_economics_config(path: Path = ECONOMICS_CONFIG) -> EconomicsRunConfig:
    """Load the fixed repository economics configuration."""
    return EconomicsRunConfig.model_validate_json(path.read_text(encoding="utf-8"))


def run_portfolio_analysis(
    workbook_path: Path,
    work_root: Path,
    progress: ProgressCallback | None = None,
    config: EconomicsRunConfig | None = None,
) -> dict[str, Any]:
    """Run the existing ingestion, damage, and alternative-analysis pipelines."""
    notify = progress or (lambda _stage, _message: None)
    work_root.mkdir(parents=True, exist_ok=True)

    notify("assets", "Building economics-ready asset features")
    asset_manifest = build_economics_asset_features(
        workbook_path,
        CADENCE_ROOT,
        work_root / "economics_assets.parquet",
    )

    notify("damage", "Calculating asset-scoped Year 1 damage")
    damage_manifest = build_asset_scoped_damage(
        workbook_path,
        WIND_RETURN_PERIODS,
        CLIMATE_ZONES,
        FRAGILITY_ROOT,
        RESULTS_ROOT / "year_1_expected_roof_damage",
    )

    notify("alternatives", "Running lifecycle alternative analysis")
    run_manifest = run_alternative_analysis_pipeline(
        pl.read_parquet(_manifest_path(asset_manifest, "output_path")),
        config if config is not None else load_economics_config(),
        pl.read_parquet(_manifest_path(damage_manifest, "asset_results_path")),
        CADENCE_ROOT,
        FRAGILITY_ROOT,
        ALTERNATIVE_RESULTS_ROOT,
        climate_delta_path=CLIMATE_DELTA,
    )
    verified = verify_run_manifest(run_manifest)
    notify("insurance", "Calculating run-linked wind-roof insurance results")
    insurance_run = publish_insurance(
        Path(verified["run_root"]),
        verified["run_metadata"],
        validate_portfolio(workbook_path).source,
        sha256_file(workbook_path),
        RESULTS_ROOT / "roof_insurance_analysis",
    )
    return {
        "workbook_path": str(workbook_path.resolve()),
        "economics_ready_asset_path": asset_manifest["output_path"],
        "asset_damage_result_path": damage_manifest["asset_results_path"],
        "asset_manifest": asset_manifest,
        "damage_manifest": damage_manifest,
        "insurance_run": insurance_run,
        **verified,
    }


def verify_run_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify that returned immutable run metadata identifies the same run."""
    required = {"run_id", "schema_version", "summary_path", "report_path"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"alternative analysis manifest is missing keys: {missing}")
    summary_path = _manifest_path(manifest, "summary_path")
    run_root = summary_path.parent.resolve()
    allowed_root = ALTERNATIVE_RESULTS_ROOT.resolve()
    if not run_root.is_relative_to(allowed_root):
        raise ValueError("alternative analysis run is outside the configured results root")
    metadata_path = run_root / "run_metadata.json"
    if not metadata_path.is_file():
        raise ValueError(f"run metadata was not written: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("run_id") != manifest["run_id"]:
        raise ValueError("returned run_id does not match run_metadata.json")
    if metadata.get("schema_version") != manifest["schema_version"]:
        raise ValueError("returned schema_version does not match run_metadata.json")
    return {
        "run_id": manifest["run_id"],
        "schema_version": manifest["schema_version"],
        "run_root": str(run_root),
        "report_path": str(_manifest_path(manifest, "report_path")),
        "run_metadata": metadata,
        "run_manifest": manifest,
    }


def _manifest_path(manifest: dict[str, Any], key: str) -> Path:
    value = manifest.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"pipeline manifest has no valid {key}")
    path = Path(value)
    if not path.exists():
        raise ValueError(f"pipeline artifact does not exist: {path}")
    return path