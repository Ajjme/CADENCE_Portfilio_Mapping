"""Command-line entry point for CADENCE roof alternative analysis."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from cadence.economics.alternative_pipeline import run_alternative_analysis_pipeline
from cadence.economics.cli import _read_table
from cadence.economics.contracts import EconomicsRunConfig


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--asset-scoped-damage", type=Path, required=True)
    parser.add_argument("--annual-loss-of-use", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--fragility-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--climate-delta", type=Path)
    arguments = parser.parse_args(argv)

    config = EconomicsRunConfig.model_validate_json(
        arguments.config.read_text(encoding="utf-8")
    )
    manifest = run_alternative_analysis_pipeline(
        _read_table(arguments.assets),
        config,
        _read_table(arguments.asset_scoped_damage),
        arguments.repository_root,
        arguments.fragility_root,
        arguments.output_root,
        annual_loss_of_use=(
            _read_table(arguments.annual_loss_of_use)
            if arguments.annual_loss_of_use is not None
            else None
        ),
        climate_delta_path=arguments.climate_delta,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()