"""Program run discovery and UI-safe artifact access."""

from pathlib import Path
from typing import Any

import pandas as pd

from cadence.program.inputs import load_inputs
from cadence.program.pipeline import load_program, publish_program
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, CADENCE_ROOT, FRAGILITY_ROOT, PROGRAM_RESULTS_ROOT


def discover_program_runs() -> list[dict[str, str]]:
    return [
        {"run_id": path.parent.name.removeprefix("run_id="), "run_root": str(path.parent.resolve())}
        for path in sorted(PROGRAM_RESULTS_ROOT.glob("schema_version=*/run_id=*/run_metadata.json"))
    ]


def create_program_run(run_root: str, asset_id: str) -> dict[str, Any]:
    root = Path(run_root).resolve()
    if not root.is_relative_to(ALTERNATIVE_RESULTS_ROOT.resolve()):
        raise ValueError("Physical run is outside the configured results root")
    return publish_program(
        load_inputs(root, asset_id, CADENCE_ROOT, FRAGILITY_ROOT), PROGRAM_RESULTS_ROOT,
    )


def load_program_results(run_root: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    root = Path(run_root).resolve()
    if not root.is_relative_to(PROGRAM_RESULTS_ROOT.resolve()):
        raise ValueError("Program run is outside the configured results root")
    metadata, candidates, annual = load_program(root)
    return metadata, candidates.to_pandas(), annual.to_pandas()
