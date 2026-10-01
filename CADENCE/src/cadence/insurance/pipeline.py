"""Publish immutable run-linked policy snapshots and annual insurance overlays."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from cadence.insurance.analysis import calculate_insurance
from cadence.insurance.contracts import normalize_policies

INSURANCE_SCHEMA = "v0.1.0"
FORMULA_VERSION = "wind_roof_annual_loss_proxy_v1"


def publish_insurance(
    physical_root: Path,
    physical_metadata: dict[str, Any],
    source: pl.DataFrame,
    workbook_checksum: str,
    output_root: Path,
) -> dict[str, Any]:
    """Use the selected workbook and completed physical run without modifying either."""
    policies = normalize_policies(source)
    run_id = physical_metadata["run_id"]
    if physical_root.name != f"run_id={run_id}" or physical_metadata["schema_version"] != "v0.4.0":
        raise ValueError("insurance requires a verified v0.4.0 physical run")
    policy_bytes = json.dumps(policies.to_dicts(), sort_keys=True, allow_nan=False).encode("utf-8")
    policy_checksum = hashlib.sha256(policy_bytes).hexdigest()
    insurance_id = hashlib.sha256(
        f"{INSURANCE_SCHEMA}:{FORMULA_VERSION}:{run_id}:{policy_checksum}:{workbook_checksum}".encode("utf-8")
    ).hexdigest()[:24]
    run_root = output_root / f"schema_version={INSURANCE_SCHEMA}" / f"run_id={insurance_id}"
    if run_root.exists():
        metadata_path = run_root / "run_metadata.json"
        if not metadata_path.is_file():
            raise ValueError("incomplete insurance artifact exists for this policy snapshot")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (metadata.get("run_id") != insurance_id
            or metadata.get("schema_version") != INSURANCE_SCHEMA
            or metadata.get("formula_version") != FORMULA_VERSION
            or metadata.get("physical_run_id") != run_id
                or metadata.get("policy_checksum") != policy_checksum
            or metadata.get("selected_workbook_sha256") != workbook_checksum
                or not (run_root / "annual_insurance").is_dir()
            or not (run_root / "policy_snapshot.parquet").is_file()
            or not (run_root / "insurance_summary.parquet").is_file()):
            raise ValueError("cached insurance artifact failed provenance checks")
        return {**metadata, "run_root": str(run_root), "cache_hit": True}

    annual_path = physical_root / "annual_alternative_analysis"
    if not annual_path.is_dir():
        raise ValueError("annual alternative analysis is unavailable")
    annual = pl.scan_parquet(
        str(annual_path / "year=*" / "*.parquet"), hive_partitioning=False
    ).select("asset_id", "year", "scenario_id", "annual_repair_cost_usd").collect()
    result = calculate_insurance(annual, policies)
    summary = result.group_by("asset_id", "scenario_id").agg(
        pl.col("year").max().alias("through_year"),
        pl.col("insurance_issue").is_not_null().sum().alias("unavailable_year_count"),
        pl.col("cumulative_margin_usd").sort_by("year").last(),
    ).sort("asset_id", "scenario_id")
    run_root.parent.mkdir(parents=True, exist_ok=True)
    staging = run_root.parent / f".{run_root.name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir()
    try:
        policies.write_parquet(staging / "policy_snapshot.parquet")
        summary.write_parquet(staging / "insurance_summary.parquet")
        for key, partition in result.partition_by("year", as_dict=True).items():
            year = key[0] if isinstance(key, tuple) else key
            year_root = staging / "annual_insurance" / f"year={year}"
            year_root.mkdir(parents=True)
            partition.write_parquet(year_root / "part-00000.parquet")
        metadata = {
            "run_id": insurance_id,
            "schema_version": INSURANCE_SCHEMA,
            "formula_version": FORMULA_VERSION,
            "physical_run_id": run_id,
            "physical_schema_version": physical_metadata["schema_version"],
            "policy_checksum": policy_checksum,
            "selected_workbook_sha256": workbook_checksum,
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_count": policies.height,
            "annual_row_count": result.height,
            "unavailable_row_count": result["insurance_issue"].is_not_null().sum(),
            "year_start": result["year"].min(),
            "year_end": result["year"].max(),
            "dollar_basis": "real_2026_usd",
            "payout_formula": "min(max(annual_repair_cost_usd - deductible_amount, 0), insured_value)",
        }
        (staging / "run_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )
        staging.rename(run_root)
    finally:
        if staging.exists():
            import shutil

            shutil.rmtree(staging)
    return {**metadata, "run_root": str(run_root), "cache_hit": False}