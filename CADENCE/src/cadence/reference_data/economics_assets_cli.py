"""Build economics-ready CADENCE asset features from an asset workbook."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from cadence.reference_data.economics_assets import build_economics_asset_features


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sheet", default="Sheet1")
    arguments = parser.parse_args(argv)
    manifest = build_economics_asset_features(
        arguments.assets,
        arguments.repository_root,
        arguments.output,
        arguments.sheet,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()