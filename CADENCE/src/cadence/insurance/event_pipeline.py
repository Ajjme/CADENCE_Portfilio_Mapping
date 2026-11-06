"""Immutable, self-contained event results; never mutate annual model artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import polars as pl

from cadence.insurance.event_analysis import (
    LIMITATIONS, EventSettings, calculate_event, summarize_event,
)

EVENT_SCHEMA = "v0.1.0"
EVENT_FORMULA = "wind_roof_deterministic_event_v1"
ARTIFACTS = (
    "input_snapshot.parquet", "event_assets.parquet", "event_portfolio.parquet",
    "event_states.parquet",
)
LOGGER = logging.getLogger(__name__)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _frame_checksum(frame: pl.DataFrame) -> str:
    return hashlib.sha256(_json_bytes(frame.to_dicts())).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_event(
    inputs: pl.DataFrame,
    settings: EventSettings,
    provenance: dict[str, Any],
    output_root: Path,
    curves: Optional[pl.DataFrame] = None,
) -> dict[str, Any]:
    inputs = inputs.sort("asset_id", "scenario_id")
    if curves is not None:
        curves = curves.sort("asset_id", "scenario_id", "wind_speed_mph")
    rows = calculate_event(inputs, settings, curves)
    identity = {
        "schema_version": EVENT_SCHEMA, "formula_version": EVENT_FORMULA,
        "settings": settings.model_dump(mode="json"), "source": provenance,
        "inputs_checksum": _frame_checksum(inputs),
        "curves_checksum": _frame_checksum(curves) if curves is not None else None,
    }
    run_id = hashlib.sha256(_json_bytes(identity)).hexdigest()[:24]
    root = output_root / f"schema_version={EVENT_SCHEMA}" / f"run_id={run_id}"
    if root.exists():
        return {**load_event(root, output_root)[0], "cache_hit": True}
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / f".{root.name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir()
    try:
        frames = {
            "input_snapshot.parquet": inputs, "event_assets.parquet": rows,
            "event_portfolio.parquet": summarize_event(rows),
            "event_states.parquet": summarize_event(rows, by_state=True),
        }
        if curves is not None:
            frames["fragility_snapshot.parquet"] = curves
        for name, frame in frames.items():
            frame.write_parquet(staging / name)
        metadata = {
            "run_id": run_id, "schema_version": EVENT_SCHEMA, "formula_version": EVENT_FORMULA,
            "identity": identity, "settings": identity["settings"],
            "physical_run_id": provenance["physical_run_id"],
            "insurance_run_id": provenance["insurance_run_id"],
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_count": inputs["asset_id"].n_unique(), "dollar_basis": "real_2026_usd",
            "gross_formula": "event_damage_ratio * active_installed_capex_usd",
            "payout_formula": "min(max(gross_event_damage_usd - deductible_amount, 0), insured_value)",
            "interpolation": "gust_200 + log(300/200)/log(500/200) * (gust_500 - gust_200); then effective fragility curve",
            "limitations": LIMITATIONS,
            "artifacts": {name: _file_checksum(staging / name) for name in frames},
        }
        (staging / "run_metadata.json").write_bytes(_json_bytes(metadata))
        staging.rename(root)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**metadata, "run_root": str(root.resolve()), "cache_hit": False}


def load_event(root: Path, output_root: Path) -> tuple[dict[str, Any], pl.DataFrame]:
    root = root.resolve()
    if not root.is_relative_to(output_root.resolve()):
        raise ValueError("event run is outside the configured results root")
    metadata = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    identity = metadata.get("identity", {})
    run_id = hashlib.sha256(_json_bytes(identity)).hexdigest()[:24]
    if (metadata.get("schema_version") != EVENT_SCHEMA
            or metadata.get("formula_version") != EVENT_FORMULA
            or identity.get("schema_version") != EVENT_SCHEMA
            or identity.get("formula_version") != EVENT_FORMULA
            or metadata.get("run_id") != run_id
            or root.name != f"run_id={run_id}"
            or root.parent.name != f"schema_version={EVENT_SCHEMA}"
            or metadata.get("settings") != identity.get("settings")
            or metadata.get("physical_run_id") != identity.get("source", {}).get("physical_run_id")
            or metadata.get("insurance_run_id") != identity.get("source", {}).get("insurance_run_id")):
        raise ValueError("event run has inconsistent identity or unsupported schema")
    settings = EventSettings.model_validate(metadata["settings"])
    expected: set[str] = set(ARTIFACTS)
    if identity.get("curves_checksum") is not None:
        expected.add("fragility_snapshot.parquet")
    if settings.return_period == 300 and "fragility_snapshot.parquet" not in expected:
        raise ValueError("300-year event is missing its curve snapshot")
    artifacts = metadata.get("artifacts", {})
    if set(artifacts) != expected:
        raise ValueError("event run has an incomplete artifact manifest")
    for name in expected:
        if _file_checksum(root / name) != artifacts[name]:
            raise ValueError(f"event artifact checksum mismatch: {name}")
    inputs = pl.read_parquet(root / "input_snapshot.parquet")
    if _frame_checksum(inputs) != identity["inputs_checksum"]:
        raise ValueError("event input snapshot does not match its identity")
    if "fragility_snapshot.parquet" in expected:
        if _frame_checksum(pl.read_parquet(root / "fragility_snapshot.parquet")) != identity["curves_checksum"]:
            raise ValueError("event curve snapshot does not match its identity")
    rows = pl.read_parquet(root / "event_assets.parquet")
    if rows.height != inputs.height or rows["asset_id"].n_unique() != metadata.get("asset_count"):
        raise ValueError("event results do not match the saved asset count")
    return {**metadata, "run_root": str(root)}, rows


def discover_events(output_root: Path, insurance_run_id: str) -> list[dict[str, Any]]:
    runs = []
    for path in output_root.glob(f"schema_version={EVENT_SCHEMA}/run_id=*/run_metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            LOGGER.warning("Cannot discover event run %s: %s", path.parent, error)
            continue
        if metadata.get("insurance_run_id") == insurance_run_id:
            runs.append({**metadata, "run_root": str(path.parent)})
    return sorted(runs, key=lambda item: item["run_timestamp"], reverse=True)
