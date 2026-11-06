"""Immutable Program artifacts that can be reopened without session inputs."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Tuple

import polars as pl

from cadence.economics.contracts import EconomicsRunConfig
from cadence.program.analysis import evaluate, summarize
from cadence.program.contracts import FORMULA_VERSION, SCHEMA_VERSION, SNAPSHOTS, ProgramInputs
from cadence.program.inputs import sha256

RESULT_FILES = ("candidates.parquet", "annual_cash_flows.parquet")
SNAPSHOT_KEYS = {
    "assets": ["asset_id"],
    "service_lives": ["official_material_id"],
    "option_costs": ["asset_id", "year", "official_material_id"],
    "removal_costs": ["asset_id", "year", "official_material_id"],
    "hazard": ["asset_id"],
    "climate": ["wind_grid_id", "year"],
    "curves": ["climate_zone", "lookup_roof_age", "source_material_id", "terrain_id", "wind_speed_mph"],
    "states": ["asset_id", "candidate_year", "year", "scenario_id"],
}


def publish_program(inputs: ProgramInputs, output_root: Path) -> Dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".program-", dir=output_root) as directory:
        stage = Path(directory)
        bundle = stage / "bundle"
        bundle.mkdir()
        for name in SNAPSHOTS:
            getattr(inputs, name).sort(SNAPSHOT_KEYS[name]).write_parquet(bundle / f"{name}.parquet")
        checksums = {f"{name}.parquet": sha256(bundle / f"{name}.parquet") for name in SNAPSHOTS}
        identity = {
            "schema_version": SCHEMA_VERSION, "formula_version": FORMULA_VERSION,
            "run_config": inputs.config.model_dump(mode="json"),
            "input_checksums": checksums, **inputs.metadata,
        }
        run_id = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]
        target = output_root / f"schema_version={SCHEMA_VERSION}" / f"run_id={run_id}"
        if target.exists():
            metadata, _, _ = load_program(target)
            if metadata["identity"] != identity:
                raise ValueError("Program cache identity mismatch")
            return {**metadata, "run_root": str(target.resolve()), "cache_hit": True}
        candidates, annual = evaluate(inputs)
        candidates.write_parquet(bundle / RESULT_FILES[0])
        annual.write_parquet(bundle / RESULT_FILES[1])
        checksums = {**checksums, **{name: sha256(bundle / name) for name in RESULT_FILES}}
        metadata = {
            "run_id": run_id, "schema_version": SCHEMA_VERSION,
            "formula_version": FORMULA_VERSION, "identity": identity,
            "run_config": inputs.config.model_dump(mode="json"), **inputs.metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checksums": checksums, "candidate_count": candidates.height,
            "annual_row_count": annual.height, "perspective": "pre_insurance_economic_proxy",
            "terminal_value": "excluded", "dollar_basis": "real_2026_usd",
            "grant_timing": "one_time_at_candidate_year",
            "cash_flow_timing": "start_of_year_installation_before_damage",
            "public_good": "not_modeled", "asset_count": 1,
        }
        (bundle / "run_metadata.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.rename(target)
    load_program(target)
    return {**metadata, "run_root": str(target.resolve()), "cache_hit": False}


def load_program(root: Path) -> Tuple[Dict[str, Any], pl.DataFrame, pl.DataFrame]:
    metadata = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("formula_version") != FORMULA_VERSION:
        raise ValueError("Unsupported Program result schema or formula")
    if root.name != f"run_id={metadata.get('run_id')}" or root.parent.name != f"schema_version={SCHEMA_VERSION}":
        raise ValueError("Program result identity does not match its directory")
    identity = metadata.get("identity")
    expected_id = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]
    if expected_id != metadata["run_id"]:
        raise ValueError("Program identity checksum mismatch")
    if any(metadata.get(key) != value for key, value in identity.items() if key != "input_checksums"):
        raise ValueError("Program metadata does not match its identity")
    files = {*(f"{name}.parquet" for name in SNAPSHOTS), *RESULT_FILES}
    checksums = metadata.get("checksums", {})
    if set(checksums) != files:
        raise ValueError("Program artifact inventory is incomplete")
    for name in files:
        if not (root / name).is_file() or sha256(root / name) != checksums[name]:
            raise ValueError(f"Program artifact is missing or corrupt: {name}")
    if any(checksums[f"{name}.parquet"] != identity["input_checksums"][f"{name}.parquet"] for name in SNAPSHOTS):
        raise ValueError("Program input checksums do not match its identity")
    config = EconomicsRunConfig.model_validate(identity["run_config"])
    if metadata["run_config"] != identity["run_config"]:
        raise ValueError("Program configuration does not match its identity")
    candidates = pl.read_parquet(root / RESULT_FILES[0])
    annual = pl.read_parquet(root / RESULT_FILES[1])
    if candidates.height != metadata["candidate_count"] or annual.height != metadata["annual_row_count"]:
        raise ValueError("Program result counts do not match metadata")
    if not summarize(annual, config).equals(candidates):
        raise ValueError("Program candidate results do not reconcile to annual cash flows")
    return metadata, candidates, annual


def load_snapshot(root: Path) -> ProgramInputs:
    metadata, _, _ = load_program(root)
    return ProgramInputs(
        config=EconomicsRunConfig.model_validate(metadata["run_config"]),
        metadata={key: value for key, value in metadata["identity"].items()
                  if key not in {"schema_version", "formula_version", "run_config", "input_checksums"}},
        **{name: pl.read_parquet(root / f"{name}.parquet") for name in SNAPSHOTS},
    )
