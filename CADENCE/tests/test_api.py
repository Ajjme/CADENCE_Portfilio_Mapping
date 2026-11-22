import io
import json
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

pytest.importorskip("fastapi", reason="needs the api and test extras")
pytest.importorskip("httpx", reason="needs the api and test extras")

from fastapi.testclient import TestClient  # noqa: E402

from cadence.api import main, service  # noqa: E402
from cadence.economics.contracts import CostStream  # noqa: E402
from cadence.economics.market_inputs import file_sha256  # noqa: E402
from cadence.economics.market_pipeline import POLICY_ID, SCHEMA_VERSION  # noqa: E402
from cadence.economics.run_export import XLSX_MIME  # noqa: E402
from cadence.economics.run_results import COST_COMPONENTS, SCENARIOS  # noqa: E402
from cadence.ui.paths import DEFAULT_WORKBOOK  # noqa: E402

RUN_ID = "api-test"
NPV = {"BASELINE_CURRENT": 0.0, "NEW_ASPHALT": 10.0, "NEW_METAL": 20.0, "NEW_TILE": -5.0}
MATERIALS = {
    "BASELINE_CURRENT": "OFFICIAL_ASPHALT",
    "NEW_ASPHALT": "OFFICIAL_ASPHALT",
    "NEW_METAL": "OFFICIAL_METAL",
    "NEW_TILE": "OFFICIAL_TILE",
}


def _write_run(results_root: Path) -> Path:
    """A one-year, two-asset run with every file the API reads."""
    root = results_root / "schema_version=v0.4.0" / f"run_id={RUN_ID}"
    partition = root / "annual_alternative_analysis" / "year=2026"
    partition.mkdir(parents=True)
    metadata = {
        "run_id": RUN_ID,
        "schema_version": "v0.4.0",
        "run_timestamp": "2026-11-22T12:00:00+00:00",
        "asset_count": 2,
        "dollar_basis": "real_2026_usd",
        "annual_analysis_path": str(root / "annual_alternative_analysis"),
        "economics_reference_run_id": "reference",
        "temporary_tile_policy": {"policy_id": "temporary_tile_as_metal_with_1_2x_cost_v1"},
        "run_config": {
            "start_year": 2026,
            "end_year": 2026,
            "real_discount_rate": 0.02,
            "enabled_cost_streams": ["material", "labor", "disposal"],
            "installed_cost_overrides": {
                material: {"material_share": 0.6, "labor_share": 0.4}
                for material in ("OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE")
            },
        },
    }
    (root / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    summary, annual = [], []
    for asset_id in ("A-1", "A-2"):
        for scenario in SCENARIOS:
            npv = None if (asset_id, scenario) == ("A-2", "NEW_TILE") else NPV[scenario]
            event = scenario != "BASELINE_CURRENT"
            summary.append({
                "asset_id": asset_id, "scenario_id": scenario, "scenario_material_id": MATERIALS[scenario],
                "through_year": 2026, "cumulative_avoided_damage_usd": 1.0,
                "cumulative_discounted_avoided_damage_usd": 1.0, "cumulative_net_benefit_usd": 1.0,
                "net_present_value_usd": npv, "burnout_replacement_count": 0,
                "active_cost_source": "source_computed_material_labor",
                "active_cost_fallback_applied": scenario == "NEW_ASPHALT", "repair_cost_incomplete": False,
                "climate_risk_total_incomplete": False, "event_cost_incomplete": False,
            })
            annual.append({
                "asset_id": asset_id, "year": 2026, "scenario_id": scenario,
                "scenario_material_id": MATERIALS[scenario], "official_current_material_id": "OFFICIAL_ASPHALT",
                "net_present_value_usd": npv, "installation_event": event,
                "initial_installation_event": event, "burnout_replacement_event": False,
                "installation_event_capex_usd": 100.0 if event else 0.0, "annual_repair_cost_usd": 20.0,
                "expected_loss_of_use_usd": None, "enabled_event_disposal_cost_usd": 5.0 if event else 0.0,
                "enabled_event_carbon_cost_usd": 0.0,
                "annual_lifecycle_cash_flow_usd": 125.0 if event else 20.0,
                "active_cost_source": "source_computed_material_labor",
                "active_cost_fallback_applied": scenario == "NEW_ASPHALT",
            })
    pl.DataFrame(summary).write_parquet(root / "alternative_summary.parquet")
    pl.DataFrame(annual).write_parquet(partition / "part-0.parquet")

    reference = results_root / "economics_reference" / "schema_version=v0.3.0" / "run_id=reference"
    reference_partition = reference / "annual_roof_option_costs" / "year=2026"
    reference_partition.mkdir(parents=True)
    (reference / "run_metadata.json").write_text(
        json.dumps({"run_id": "reference", "schema_version": "v0.3.0"}), encoding="utf-8"
    )
    pl.DataFrame([
        {"asset_id": asset_id, "year": 2026, "official_material_id": material,
         "source_material_usd_per_sqft": 7.0, "source_labor_usd_per_sqft": 3.0}
        for asset_id in ("A-1", "A-2")
        for material in ("OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_TILE")
    ]).write_parquet(reference_partition / "part-0.parquet")
    return root


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    results_root = tmp_path / "roof_alternative_analysis"
    _write_run(results_root)
    monkeypatch.setattr(service, "ALTERNATIVE_RESULTS_ROOT", results_root)
    monkeypatch.setattr(service, "API_WORK_ROOT", tmp_path / "api")
    monkeypatch.setattr(service, "UPLOAD_ROOT", tmp_path / "api" / "uploads")
    return TestClient(main.app)


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_settings_come_from_the_repository_config(client: TestClient) -> None:
    settings = client.get("/api/settings").json()

    assert settings["first_year"] == 2026 and settings["last_year"] == 2050
    assert settings["cost_streams"] == ["disposal", "carbon"]
    assert settings["scghg_discount_rate_options"] == [1.5, 2.0, 2.5]
    assert settings["metrics"]["net_present_value_usd"] == "Net present value"


def test_run_info(client: TestClient) -> None:
    run = client.get(f"/api/runs/{RUN_ID}").json()

    assert run["market_study_ready"] is False

    assert run["run_id"] == RUN_ID
    assert run["asset_count"] == 2
    assert (run["start_year"], run["end_year"]) == (2026, 2026)
    assert run["enabled_cost_streams"] == ["disposal", "labor", "material"]


def test_unknown_or_malformed_run_ids_are_not_found(client: TestClient) -> None:
    assert client.get("/api/runs/missing").status_code == 404
    assert client.get("/api/runs/bad.id/summary").status_code == 404


def test_summary_totals_npv_and_keeps_missing_totals_empty(client: TestClient) -> None:
    summary = client.get(f"/api/runs/{RUN_ID}/summary").json()
    portfolio = {row["scenario_id"]: row for row in summary["portfolio"]}

    assert len(summary["assets"]) == 8
    assert portfolio["NEW_METAL"]["net_present_value_usd"] == 40.0
    assert portfolio["NEW_METAL"]["asset_count"] == 2
    # A-2 has no Tile NPV, so the portfolio total is left empty instead of undercounting.
    assert portfolio["NEW_TILE"]["net_present_value_usd"] is None
    assert portfolio["NEW_ASPHALT"]["active_cost_fallback_applied"] is True


def test_series_for_the_portfolio_and_one_asset(client: TestClient) -> None:
    portfolio = client.get(f"/api/runs/{RUN_ID}/series").json()
    asset = client.get(f"/api/runs/{RUN_ID}/series", params={"asset_id": "A-1"}).json()

    assert portfolio["metric"] == "net_present_value_usd"
    assert portfolio["asset_id"] is None
    points = {point["scenario_id"]: point for point in portfolio["points"]}
    assert points["NEW_METAL"] == {
        "year": 2026, "scenario_id": "NEW_METAL", "value": 40.0, "installation_events": 2, "replacement_events": 0,
    }
    assert points["NEW_TILE"]["value"] is None
    assert {point["scenario_id"]: point["value"] for point in asset["points"]}["NEW_METAL"] == 20.0


def test_series_rejects_unknown_assets_and_metrics(client: TestClient) -> None:
    assert client.get(f"/api/runs/{RUN_ID}/series", params={"asset_id": "nope"}).status_code == 404
    response = client.get(f"/api/runs/{RUN_ID}/series", params={"metric": "made_up"})
    assert response.status_code == 400
    assert "made_up" in response.json()["detail"]


def test_cost_allocations_split_each_option(client: TestClient) -> None:
    costs = client.get(f"/api/runs/{RUN_ID}/cost-allocations", params={"year": 2026}).json()
    rows = {row["scenario_id"]: row for row in costs["rows"]}

    assert list(costs["labels"]) == list(COST_COMPONENTS)
    assert set(rows) == set(SCENARIOS)
    # Two assets, each with $100 of capex split 7:3 by the source prices.
    assert rows["NEW_METAL"]["material_usd"] == pytest.approx(140.0)
    assert rows["NEW_METAL"]["labor_usd"] == pytest.approx(60.0)
    assert rows["NEW_METAL"]["disposal_usd"] == pytest.approx(10.0)
    assert rows["NEW_METAL"]["carbon_usd"] == 0.0
    assert rows["NEW_ASPHALT"]["allocation_estimated"] is True
    assert rows["BASELINE_CURRENT"]["material_usd"] == 0.0


def test_cost_allocations_for_one_asset_and_outside_the_run_years(client: TestClient) -> None:
    asset = client.get(f"/api/runs/{RUN_ID}/cost-allocations", params={"year": 2026, "asset_id": "A-1"}).json()
    assert asset["asset_id"] == "A-1"
    assert {row["scenario_id"]: row["material_usd"] for row in asset["rows"]}["NEW_METAL"] == pytest.approx(70.0)

    response = client.get(f"/api/runs/{RUN_ID}/cost-allocations", params={"year": 2030})
    assert response.status_code == 400


def test_export_downloads_the_run_workbook(client: TestClient) -> None:
    response = client.get(f"/api/runs/{RUN_ID}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MIME
    assert f"cadence_results_{RUN_ID}.xlsx" in response.headers["content-disposition"]
    sheets = pd.read_excel(io.BytesIO(response.content), sheet_name=None)
    assert "Portfolio summary" in sheets


def test_example_and_default_portfolio(client: TestClient) -> None:
    example = client.get("/api/portfolio/example")
    portfolio = client.get("/api/portfolio/default").json()

    assert example.content == DEFAULT_WORKBOOK.read_bytes()
    assert portfolio["workbook_id"] == "default"
    assert portfolio["asset_count"] == len(portfolio["assets"]) > 0
    assert {"asset_id", "official_material"} <= set(portfolio["assets"][0])


def test_upload_saves_the_workbook_under_its_checksum(client: TestClient, tmp_path: Path) -> None:
    upload = {"file": ("my_assets.xlsx", DEFAULT_WORKBOOK.read_bytes(), XLSX_MIME)}
    portfolio = client.post("/api/portfolio", files=upload).json()

    assert portfolio["file_name"] == "my_assets.xlsx"
    assert len(portfolio["workbook_id"]) == 64
    assert (tmp_path / "api" / "uploads" / f"{portfolio['workbook_id']}.xlsx").is_file()

    wrong_type = client.post("/api/portfolio", files={"file": ("assets.csv", b"a,b", "text/csv")})
    assert wrong_type.status_code == 400


def test_run_uses_the_selected_assets_and_settings(client: TestClient, monkeypatch) -> None:
    calls = []

    def fake_analysis(workbook, work_root, progress=None, config=None):
        calls.append({"workbook": workbook, "config": config})
        return {"run_id": RUN_ID, "run_root": "anywhere", **_study_files(work_root)}

    monkeypatch.setattr(service, "run_portfolio_analysis", fake_analysis)
    first_asset = client.get("/api/portfolio/default").json()["assets"][0]["asset_id"]

    response = client.post("/api/runs", json={
        "asset_ids": [first_asset],
        "settings": {"end_year": 2030, "cost_streams": [], "demand_surge": True},
    })

    assert response.status_code == 200
    assert response.json()["run_id"] == RUN_ID
    config = calls[0]["config"]
    assert config.end_year == 2030 and config.demand_surge is True
    assert config.enabled_cost_streams == frozenset({CostStream.MATERIAL, CostStream.LABOR})
    assert calls[0]["workbook"].name == "selected_assets.xlsx"
    # The run's asset files are kept for the Market Study.
    assert response.json()["market_study_ready"] is True


def test_run_rejects_bad_settings_and_unknown_workbooks(client: TestClient) -> None:
    bad_rate = client.post("/api/runs", json={"settings": {"scghg_discount_rate": 3.0}})
    missing = client.post("/api/runs", json={"workbook_id": "0" * 64})

    assert bad_rate.status_code == 400
    assert missing.status_code == 404


def test_the_frontend_schema_matches_the_api() -> None:
    from cadence.api import write_openapi

    fix = "the API changed - run `python -m cadence.api.write_openapi`, then `npm run api:types` in frontend/"
    assert write_openapi.SCHEMA_PATH.is_file(), fix
    saved = json.loads(write_openapi.SCHEMA_PATH.read_text(encoding="utf-8"))
    current = json.loads(write_openapi.schema_text())
    assert saved["paths"] == current["paths"], fix
    assert saved["components"] == current["components"], fix


def _study_files(folder: Path) -> dict:
    """Stand-ins for the asset files a real run saves, which the Market Study reads."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key in ("economics_ready_asset_path", "asset_damage_result_path"):
        path = folder / f"{key}.parquet"
        path.write_bytes(b"stand-in")
        paths[key] = str(path)
    return paths


def _save_study_inputs(tmp_path: Path) -> None:
    inputs = tmp_path / "api" / "run_inputs" / f"{RUN_ID}.json"
    inputs.parent.mkdir(parents=True)
    inputs.write_text(
        json.dumps({"run_id": RUN_ID, "run_root": "anywhere", **_study_files(tmp_path / "inputs")}),
        encoding="utf-8",
    )


def _write_study(study_root: Path, run_root: Path) -> Path:
    """A saved two-asset, two-year Market Study, like run_market_study publishes."""
    folder = study_root / f"schema_version={SCHEMA_VERSION}" / "run_id=study-test"
    folder.mkdir(parents=True)
    pl.DataFrame({
        "year": [2026, 2026, 2027, 2027],
        "material_id": ["OFFICIAL_ASPHALT", "OFFICIAL_METAL", "OFFICIAL_METAL", "UNKNOWN"],
        "asset_count": [1, 1, 1, 1],
        "portfolio_count": [2, 2, 2, 2],
        "share_percent": [50.0, 50.0, 50.0, 50.0],
    }).write_parquet(folder / "annual_roof_share.parquet")
    pl.DataFrame({
        "year": [2026, 2027],
        "repair_usd": [20.0, 25.0], "loss_of_use_usd": [0.0, 0.0],
        "material_usd": [70.0, 0.0], "labor_usd": [30.0, 0.0],
        "disposal_usd": [5.0, 0.0], "carbon_usd": [0.0, 0.0],
        "total_usd": [125.0, None],
        "replacement_count": [1, 0], "eul_replacements": [0, 0], "damage_replacements": [0, 0],
        "economic_replacements": [1, 0], "unknown_count": [0, 1],
    }).write_parquet(folder / "annual_portfolio_costs.parquet")
    manifest = {
        "run_id": "study-test", "schema_version": SCHEMA_VERSION, "policy_id": POLICY_ID,
        "parent_run_id": RUN_ID, "parent_run_root": str(run_root.resolve()),
        "run_config": {"real_discount_rate": 0.02, "enabled_cost_streams": ["material", "labor"]},
        "temporary_tile_policy": {"policy_id": "temporary_tile_as_metal_with_1_2x_cost_v1"},
        "asset_count": 2, "max_payback_years": 5,
        "last_verified_year": 2027, "evaluation_end_year": 2060,
        "artifact_checksums": {
            name: file_sha256(folder / name)
            for name in ("annual_roof_share.parquet", "annual_portfolio_costs.parquet")
        },
    }
    (folder / "run_metadata.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_market_study_needs_a_run_started_from_the_portfolio_page(client: TestClient) -> None:
    saved = client.get(f"/api/runs/{RUN_ID}/market-study")
    run = client.post(f"/api/runs/{RUN_ID}/market-study", json={})

    assert saved.status_code == run.status_code == 404
    assert "Asset Portfolio page" in run.json()["detail"]


def test_market_study_runs_and_returns_roof_shares_and_costs(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    _save_study_inputs(tmp_path)
    run_root = tmp_path / "roof_alternative_analysis" / "schema_version=v0.4.0" / f"run_id={RUN_ID}"
    study = _write_study(tmp_path / "studies", run_root)
    monkeypatch.setattr(service, "STUDY_ROOT", tmp_path / "studies")
    calls = []

    def fake_study(parent_root, inputs, max_payback_years):
        calls.append((parent_root, inputs, max_payback_years))
        return {"run_root": str(study), "cache_hit": False}

    monkeypatch.setattr(service, "run_market_study", fake_study)

    result = client.post(f"/api/runs/{RUN_ID}/market-study", json={"max_payback_years": 5}).json()

    assert calls[0][2] == 5
    assert calls[0][1]["run_id"] == RUN_ID
    assert Path(calls[0][1]["economics_ready_asset_path"]).is_file()
    assert result["study_id"] == "study-test"
    assert result["newly_calculated"] is True
    assert result["tile_uses_metal_proxy"] is True
    assert list(result["cost_labels"])[:2] == ["repair_usd", "loss_of_use_usd"]
    assert len(result["roof_share"]) == 4
    assert result["costs"][0]["material_usd"] == 70.0
    assert result["costs"][1]["total_usd"] is None
    assert client.get(f"/api/runs/{RUN_ID}").json()["market_study_ready"] is True


def test_saved_market_study_opens_without_running_again(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    _save_study_inputs(tmp_path)
    run_root = tmp_path / "roof_alternative_analysis" / "schema_version=v0.4.0" / f"run_id={RUN_ID}"
    study = _write_study(tmp_path / "studies", run_root)
    monkeypatch.setattr(service, "STUDY_ROOT", tmp_path / "studies")
    monkeypatch.setattr(service, "study_identity", lambda *_: {"max_payback_years": 5})
    monkeypatch.setattr(service, "run_market_study", lambda *_: pytest.fail("should not run"))

    monkeypatch.setattr(service, "study_path", lambda _identity: study)
    saved = client.get(f"/api/runs/{RUN_ID}/market-study", params={"max_payback_years": 5})
    monkeypatch.setattr(service, "study_path", lambda _identity: tmp_path / "studies" / "missing")
    missing = client.get(f"/api/runs/{RUN_ID}/market-study")

    assert saved.status_code == 200
    assert saved.json()["newly_calculated"] is False
    assert missing.status_code == 404
    assert "hasn't been run" in missing.json()["detail"]
