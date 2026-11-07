"""Where the precomputed reference files live, and whether they are usable.

precompute.py writes small versions of the large raw inputs to Data/Precomputed.
The pipeline readers use them when they are there and fall back to the raw
files when they are not, so a checkout without them still works, just slower.
Rerun the precompute script whenever a raw input changes.
"""

from pathlib import Path
from typing import Optional

PRECOMPUTED_DIRNAME = "Precomputed"
WIND_FILE = "wind_return_periods.parquet"
ZIP_LOOKUP_FILE = "zcta_county_cbsa.parquet"
ZIP_BOUNDARIES_LOOKUP_FILE = "zcta_boundaries_lookup.parquet"
ZIP_BOUNDARIES_MAP_FILE = "zcta_boundaries_map.parquet"
FRAGILITY_FILE = "fragility_curves.parquet"
LFS_POINTER_PREFIX = b"version https://git-lfs"


def precomputed_root(data_root: Path) -> Path:
    """Data/Precomputed, given the Data folder."""
    return data_root / PRECOMPUTED_DIRNAME


def usable_file(path: Path) -> Optional[Path]:
    """Return the path if it is a real file, or None if it is missing or only a Git LFS pointer."""
    if not path.is_file():
        return None
    with path.open("rb") as source:
        if source.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX:
            return None
    return path


def precomputed_file(data_root: Path, name: str) -> Optional[Path]:
    """The precomputed file with this name under Data/Precomputed, if it is usable."""
    return usable_file(precomputed_root(data_root) / name)
