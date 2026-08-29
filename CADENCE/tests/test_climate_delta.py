from pathlib import Path

import polars as pl
import pytest

from cadence.reference_data.climate_delta import (
    GRID_ID_MULTIPLIER,
    resolve_climate_scale_factors,
)


def _write_delta(path: Path, **overrides: list) -> None:
    values = {
        "lat_idx": [1, 2],
        "lon_idx": [10, 20],
        "scale_2025": [0.9, 1.0],
        "scale_2040": [1.0, 1.1],
        "scale_2050": [1.2, 1.3],
    }
    values.update(overrides)
    pl.DataFrame(values).write_parquet(path)


def test_resolves_baseline_source_and_extrapolated_factors(tmp_path: Path) -> None:
    path = tmp_path / "delta.parquet"
    _write_delta(path)
    grid_id = GRID_ID_MULTIPLIER + 10
    keys = pl.DataFrame(
        {"wind_grid_id": [grid_id] * 4, "year": [2024, 2025, 2050, 2052]}
    )

    result = resolve_climate_scale_factors(path, keys)

    assert result["climate_scale_factor"].to_list() == pytest.approx(
        [1.0, 0.9, 1.2, 1.24]
    )
    assert result["climate_scale_rule"].to_list() == [
        "baseline",
        "source_year",
        "source_year",
        "linear_2040_2050_extrapolation",
    ]


@pytest.mark.parametrize("invalid_factor", [None, float("nan"), 0.0, -0.1])
def test_rejects_invalid_factors(tmp_path: Path, invalid_factor: float) -> None:
    path = tmp_path / "delta.parquet"
    _write_delta(path, scale_2025=[invalid_factor, 1.0])

    with pytest.raises(ValueError, match="finite and positive"):
        resolve_climate_scale_factors(
            path,
            pl.DataFrame(
                {"wind_grid_id": [GRID_ID_MULTIPLIER + 10], "year": [2025]}
            ),
        )


def test_rejects_missing_grid_and_year_column(tmp_path: Path) -> None:
    path = tmp_path / "delta.parquet"
    _write_delta(path)

    with pytest.raises(ValueError, match="missing selected wind grid IDs"):
        resolve_climate_scale_factors(
            path,
            pl.DataFrame({"wind_grid_id": [999], "year": [2025]}),
        )
    with pytest.raises(ValueError, match="scale_2026"):
        resolve_climate_scale_factors(
            path,
            pl.DataFrame(
                {"wind_grid_id": [GRID_ID_MULTIPLIER + 10], "year": [2026]}
            ),
        )


def test_rejects_duplicate_grid_keys(tmp_path: Path) -> None:
    path = tmp_path / "delta.parquet"
    _write_delta(path, lat_idx=[1, 1], lon_idx=[10, 10])

    with pytest.raises(ValueError, match="duplicate selected grid keys"):
        resolve_climate_scale_factors(
            path,
            pl.DataFrame(
                {"wind_grid_id": [GRID_ID_MULTIPLIER + 10], "year": [2025]}
            ),
        )