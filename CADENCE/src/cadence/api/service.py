"""What each API endpoint does, in plain Python.

main.py only turns web requests into calls to these functions and their results
into responses, so this file is where to look to change how the backend works.
Everything here reuses the code the Streamlit app runs: the same workbook checks,
the same pipeline, and the same run reads (cadence.economics.run_results).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Optional

import duckdb
import pandas as pd

from cadence.api.schemas import (
    CostAllocations,
    Portfolio,
    RunInfo,
    RunRequest,
    RunSettings,
    RunSummary,
    Series,
    SettingsChoices,
)
from cadence.economics import run_results
from cadence.economics.contracts import END_YEAR, START_YEAR, CostStream, EconomicsRunConfig
from cadence.economics.run_export import build_run_workbook, portfolio_summary
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT, CADENCE_ROOT, DEFAULT_WORKBOOK
from cadence.ui.pipeline import load_economics_config, run_portfolio_analysis
from cadence.ui.workbooks import materialize_filtered_workbook, save_uploaded_workbook, validate_portfolio

DEFAULT_WORKBOOK_ID = "default"
# Uploaded workbooks and each run's working files. Like the Streamlit app's
# session folder, nothing here is kept on purpose - most hosts wipe it on restart.
API_WORK_ROOT = CADENCE_ROOT / "cadence_datalake" / "api"
UPLOAD_ROOT = API_WORK_ROOT / "uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SCGHG_RATES = [1.5, 2.0, 2.5]
OPTIONAL_COST_STREAMS = (CostStream.DISPOSAL, CostStream.CARBON)
ALWAYS_ON_COST_STREAMS = (CostStream.MATERIAL, CostStream.LABOR)
# Run IDs are short hex strings. Checking the shape keeps a request from reaching other folders.
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
WORKBOOK_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

# One analysis at a time. A run reads and writes shared result folders and uses
# most of a small server's memory, so a second request waits for the first.
_run_lock = threading.Lock()


class NotFoundError(LookupError):
    """The run, asset, or workbook a request asked for doesn't exist. Sent back as a 404."""


class UploadTooLargeError(ValueError):
    """Sent back as a 413."""


def allowed_origins() -> list[str]:
    """Web addresses allowed to call the API from a browser.

    Defaults to the Vite dev server. Set CADENCE_API_ORIGINS (comma-separated) to replace the list.
    """
    configured = os.environ.get("CADENCE_API_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


# Settings


def default_settings() -> SettingsChoices:
    config = load_economics_config()
    enabled = set(config.enabled_cost_streams)
    return SettingsChoices(
        start_year=config.start_year,
        end_year=config.end_year,
        real_discount_rate=config.real_discount_rate,
        scghg_discount_rate=config.scghg_discount_rate,
        demand_surge=config.demand_surge,
        cost_streams=[stream.value for stream in OPTIONAL_COST_STREAMS if stream in enabled],
        first_year=START_YEAR,
        last_year=END_YEAR,
        scghg_discount_rate_options=SCGHG_RATES,
        optional_cost_streams=[stream.value for stream in OPTIONAL_COST_STREAMS],
        metrics=dict(run_results.METRICS),
    )


def configure_run(settings: RunSettings) -> EconomicsRunConfig:
    """The repository's economics config with the user's choices on top, the same way the Streamlit page builds it."""
    values = load_economics_config().model_dump(mode="json")
    values.update(settings.model_dump(exclude_none=True, exclude={"cost_streams"}))
    if settings.cost_streams is not None:
        streams = {stream.value for stream in ALWAYS_ON_COST_STREAMS} | set(settings.cost_streams)
        values["enabled_cost_streams"] = sorted(streams)
    return EconomicsRunConfig.model_validate(values)


# Portfolio workbooks


def save_workbook(upload: BinaryIO, file_name: Optional[str]) -> str:
    """Save an uploaded workbook under its checksum and return that as its ID."""
    if not (file_name or "").lower().endswith(".xlsx"):
        raise ValueError("upload an Excel workbook (.xlsx)")
    payload = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise UploadTooLargeError(f"workbook is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    workbook_id = hashlib.sha256(payload).hexdigest()
    path = UPLOAD_ROOT / f"{workbook_id}.xlsx"
    if not path.exists():
        save_uploaded_workbook(io.BytesIO(payload), path)
    return workbook_id


def workbook_path(workbook_id: str) -> Path:
    if workbook_id == DEFAULT_WORKBOOK_ID:
        return DEFAULT_WORKBOOK
    if not WORKBOOK_ID_PATTERN.fullmatch(workbook_id):
        raise NotFoundError(f"no workbook with ID {workbook_id!r}")
    path = UPLOAD_ROOT / f"{workbook_id}.xlsx"
    if not path.is_file():
        raise NotFoundError(f"no workbook with ID {workbook_id!r} - upload it again")
    return path


def portfolio(workbook_id: str, file_name: Optional[str] = None) -> Portfolio:
    """Check a workbook the same way the Streamlit Asset Portfolio page does and return its assets."""
    path = workbook_path(workbook_id)
    assets = validate_portfolio(path).display.to_pandas()
    return Portfolio(
        workbook_id=workbook_id,
        file_name=file_name or path.name,
        asset_count=len(assets),
        assets=records(assets),
    )


# Runs


def start_run(request: RunRequest) -> RunInfo:
    """Run the full analysis (assets, damage, alternatives, insurance) and return the new run."""
    source = workbook_path(request.workbook_id)
    config = configure_run(request.settings)
    work_root = API_WORK_ROOT / "analyses" / uuid.uuid4().hex
    workbook = source
    if request.asset_ids is not None:
        workbook = materialize_filtered_workbook(source, work_root / "selected_assets.xlsx", request.asset_ids)
    with _run_lock:
        result = run_portfolio_analysis(workbook, work_root, config=config)
    _run_root, metadata = find_run(result["run_id"])
    return run_info(metadata)


def find_run(run_id: str) -> tuple[Path, dict[str, Any]]:
    """The run's folder and checked metadata."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise NotFoundError(f"no run with ID {run_id!r}")
    matches = sorted(ALTERNATIVE_RESULTS_ROOT.glob(f"schema_version=*/run_id={run_id}"))
    if not matches:
        raise NotFoundError(f"no run with ID {run_id!r}")
    if len(matches) > 1:
        raise ValueError(f"more than one saved run has the ID {run_id!r}")
    return matches[0], run_results.check_run_metadata(matches[0], ALTERNATIVE_RESULTS_ROOT)


def run_info(metadata: dict[str, Any]) -> RunInfo:
    config = metadata.get("run_config") or {}
    return RunInfo(
        run_id=metadata["run_id"],
        schema_version=metadata["schema_version"],
        run_timestamp=metadata.get("run_timestamp"),
        asset_count=metadata["asset_count"],
        start_year=config["start_year"],
        end_year=config["end_year"],
        real_discount_rate=config.get("real_discount_rate"),
        scghg_discount_rate=config.get("scghg_discount_rate"),
        demand_surge=config.get("demand_surge"),
        enabled_cost_streams=sorted(config.get("enabled_cost_streams") or []),
        dollar_basis=metadata.get("dollar_basis"),
    )


def run_summary(run_id: str, connection: duckdb.DuckDBPyConnection) -> RunSummary:
    """Final results by asset and replacement option, plus portfolio totals (NPV and the rest)."""
    run_root, _metadata = find_run(run_id)
    summary = run_results.read_summary(run_root, connection)
    return RunSummary(
        run_id=run_id,
        portfolio=records(portfolio_summary(summary)),
        assets=records(summary),
    )


def run_series(
    run_id: str, metric: str, asset_id: Optional[str], connection: duckdb.DuckDBPyConnection
) -> Series:
    """One yearly result for each replacement option, for one asset or the whole portfolio."""
    run_results.validate_metric(metric)
    run_root, metadata = find_run(run_id)
    if asset_id is None:
        rows = run_results.read_portfolio_series(run_root, metadata, metric, connection)
        installations = rows["installation_event_count"]
        replacements = rows["replacement_event_count"]
    else:
        rows = run_results.read_asset_series(run_root, metadata, asset_id, metric, connection)
        if rows.empty:
            raise NotFoundError(f"asset {asset_id!r} is not in run {run_id}")
        installations = rows["installation_event"].fillna(False).astype(int)
        replacements = rows["burnout_replacement_event"].fillna(False).astype(int)
    points = pd.DataFrame({
        "year": rows["year"],
        "scenario_id": rows["scenario_id"],
        "value": rows["metric_value"],
        "installation_events": installations,
        "replacement_events": replacements,
    })
    return Series(
        run_id=run_id,
        asset_id=asset_id,
        metric=metric,
        label=run_results.METRICS[metric],
        points=records(points),
    )


def run_cost_allocations(
    run_id: str, year: int, asset_id: Optional[str], connection: duckdb.DuckDBPyConnection
) -> CostAllocations:
    """One year's costs for each replacement option, split into material, labor, repair, and the rest."""
    run_root, metadata = find_run(run_id)
    portfolio_wide = asset_id is None
    rows = run_results.read_year_cost_rows(
        run_root, metadata, year, run_results.PORTFOLIO_OPTION if portfolio_wide else asset_id, connection
    )
    allocations = run_results.cost_allocations(rows, metadata, portfolio_wide)
    columns = ["scenario_id", *run_results.COST_COMPONENTS, "total_usd", "allocation_estimated"]
    return CostAllocations(
        run_id=run_id,
        asset_id=asset_id,
        year=year,
        labels=dict(run_results.COST_COMPONENTS),
        rows=records(allocations[columns]),
    )


def run_workbook(run_id: str) -> tuple[bytes, str]:
    """The run as one Excel file (same as the Streamlit download), and its file name."""
    run_root, metadata = find_run(run_id)
    return build_run_workbook(run_root), f"cadence_results_{metadata['run_id']}.xlsx"


# Helpers


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain JSON values. Missing numbers become null and dates become ISO text."""
    return json.loads(frame.to_json(orient="records", date_format="iso") or "[]")

