"""Where the precomputed reference files live, and whether they are usable.

precompute.py writes small versions of the large raw inputs to Data/Precomputed.
The pipeline readers use them when they are there and fall back to the raw
files when they are not, so a checkout without them still works, just slower.
Rerun the precompute script whenever a raw input changes.

The same files are also kept in a Cloudflare R2 bucket. When the
CADENCE_DATA_URL setting points at them, download_precomputed_files() fetches
any file this checkout doesn't have, so a server doesn't need Git LFS.
"""

import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, Optional

PRECOMPUTED_DIRNAME = "Precomputed"
WIND_FILE = "wind_return_periods.parquet"
ZIP_LOOKUP_FILE = "zcta_county_cbsa.parquet"
ZIP_BOUNDARIES_LOOKUP_FILE = "zcta_boundaries_lookup.parquet"
ZIP_BOUNDARIES_MAP_FILE = "zcta_boundaries_map.parquet"
FRAGILITY_FILE = "fragility_curves.parquet"
LFS_POINTER_PREFIX = b"version https://git-lfs"
MANIFEST_FILE = "manifest.json"
# Where the files are online, like https://pub-....r2.dev/precomputed/v1
DATA_URL_SETTING = "CADENCE_DATA_URL"
# Cloudflare refuses Python's default user agent ("Python-urllib") as a bot, so downloads name themselves.
USER_AGENT = "cadence-data-download/1.0"


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


def expected_files(manifest: dict) -> dict[str, int]:
    """Each precomputed file's name and size in bytes, as manifest.json records them."""
    files = {}
    for output in manifest["outputs"].values():
        if "file" in output:
            files[output["file"]] = output["bytes"]
        # The ZIP boundaries come as two files, one for the lookup and one for the map.
        for kind in ("lookup", "map"):
            if f"{kind}_file" in output:
                files[output[f"{kind}_file"]] = output[f"{kind}_bytes"]
    return files


def _open_url(url: str, timeout: float):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def download_precomputed_files(
    data_root: Path,
    base_url: Optional[str] = None,
    open_url: Callable = _open_url,
) -> list[str]:
    """Download each precomputed file this checkout is missing (or has only as a Git LFS pointer).

    Files come from base_url, or the CADENCE_DATA_URL setting, and nothing is
    downloaded when neither is set. Each download is checked against the size
    in manifest.json, which is in git, so a file that doesn't match is never used.
    Returns the names of the files it downloaded.
    """
    base_url = base_url or os.environ.get(DATA_URL_SETTING)
    if not base_url:
        return []
    root = precomputed_root(data_root)
    manifest = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
    downloaded = []
    for name, size in expected_files(manifest).items():
        path = root / name
        if usable_file(path) and path.stat().st_size == size:
            continue
        partial = path.with_name(path.name + ".part")
        with open_url(f"{base_url.rstrip('/')}/{name}", timeout=300) as response, partial.open("wb") as target:
            shutil.copyfileobj(response, target, 1024 * 1024)
        if partial.stat().st_size != size:
            got = partial.stat().st_size
            partial.unlink()
            raise RuntimeError(f"{name} from {base_url} is {got} bytes, but manifest.json says {size}")
        os.replace(partial, path)
        print(f"Downloaded {name} ({size / 1e6:.1f} MB) from {base_url}", flush=True)
        downloaded.append(name)
    return downloaded
