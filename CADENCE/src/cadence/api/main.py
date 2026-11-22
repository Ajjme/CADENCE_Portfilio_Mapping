"""The CADENCE backend: a small FastAPI app that the React frontend calls.

Run it from the CADENCE folder:

    uvicorn cadence.api.main:app --reload

then open http://127.0.0.1:8000/docs to see and try every endpoint.

Each endpoint below only reads the request and calls one function in service.py,
which does the work. The URLs all start with /api so the frontend can tell
backend calls apart from its own pages.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Optional

import duckdb
from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from cadence.api import service
from cadence.api.schemas import (
    CostAllocations,
    Health,
    Portfolio,
    RunInfo,
    RunRequest,
    RunSummary,
    Series,
    SettingsChoices,
)
from cadence.economics.run_export import XLSX_MIME
from cadence.ui.paths import DEFAULT_WORKBOOK

app = FastAPI(
    title="CADENCE API",
    version="0.1.0",
    description="Runs CADENCE roof Alternative Analyses and serves their results to the frontend.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=service.allowed_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# Errors from service.py become plain JSON messages the frontend can show.


@app.exception_handler(service.NotFoundError)
async def not_found(_request: Request, error: service.NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(service.UploadTooLargeError)
async def too_large(_request: Request, error: service.UploadTooLargeError) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(error)})


@app.exception_handler(ValueError)
async def bad_request(_request: Request, error: ValueError) -> JSONResponse:
    # The pipeline and its checks raise ValueError with a message meant for the user.
    return JSONResponse(status_code=400, content={"detail": str(error)})


def duckdb_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """A fresh in-memory DuckDB connection for each request, closed afterwards.

    Requests can run at the same time on different threads, and one DuckDB
    connection shouldn't be shared across threads. Opening one is quick.
    """
    connection = duckdb.connect()
    try:
        yield connection
    finally:
        connection.close()


Connection = Annotated[duckdb.DuckDBPyConnection, Depends(duckdb_connection)]
AssetId = Annotated[Optional[str], Query(description="One asset. Leave out for the whole portfolio.")]


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health()


@app.get("/api/settings", response_model=SettingsChoices)
def settings() -> SettingsChoices:
    """Default run settings and the allowed values, for the settings form."""
    return service.default_settings()


@app.get("/api/portfolio/example")
def example_workbook() -> FileResponse:
    """Download the example asset workbook, to use as a template."""
    return FileResponse(DEFAULT_WORKBOOK, media_type=XLSX_MIME, filename=DEFAULT_WORKBOOK.name)


@app.get("/api/portfolio/default", response_model=Portfolio)
def default_portfolio() -> Portfolio:
    """The example workbook's assets, shown before anyone uploads their own."""
    return service.portfolio(service.DEFAULT_WORKBOOK_ID)


@app.post("/api/portfolio", response_model=Portfolio)
def upload_portfolio(file: Annotated[UploadFile, File(description="CADENCE asset workbook (.xlsx)")]) -> Portfolio:
    """Upload and check an asset workbook. Use the returned workbook_id to run it."""
    workbook_id = service.save_workbook(file.file, file.filename)
    return service.portfolio(workbook_id, file.filename)


@app.post("/api/runs", response_model=RunInfo)
def run_analysis(request: RunRequest) -> RunInfo:
    """Run the Alternative Analysis. This waits until the run finishes, which can take a few minutes."""
    return service.start_run(request)


@app.get("/api/runs/{run_id}", response_model=RunInfo)
def run(run_id: str) -> RunInfo:
    _run_root, metadata = service.find_run(run_id)
    return service.run_info(metadata)


@app.get("/api/runs/{run_id}/summary", response_model=RunSummary)
def run_summary(run_id: str, connection: Connection) -> RunSummary:
    """Final NPV and the other results, by asset and replacement option, plus portfolio totals."""
    return service.run_summary(run_id, connection)


@app.get("/api/runs/{run_id}/series", response_model=Series)
def run_series(
    run_id: str,
    connection: Connection,
    asset_id: AssetId = None,
    metric: Annotated[str, Query(description="A key from GET /api/settings metrics")] = "net_present_value_usd",
) -> Series:
    """One yearly result for each replacement option, for the time series chart."""
    return service.run_series(run_id, metric, asset_id, connection)


@app.get("/api/runs/{run_id}/cost-allocations", response_model=CostAllocations)
def run_cost_allocations(
    run_id: str,
    year: int,
    connection: Connection,
    asset_id: AssetId = None,
) -> CostAllocations:
    """One year's costs for each replacement option, for the cost allocation chart."""
    return service.run_cost_allocations(run_id, year, asset_id, connection)


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str) -> Response:
    """Download the whole run as one Excel file."""
    content, file_name = service.run_workbook(run_id)
    return Response(
        content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
