import json
from pathlib import Path
from types import SimpleNamespace

import polars as pl

from cadence.ui import pipeline


def test_verify_run_manifest_uses_returned_paths(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "schema_version=v0.4.0" / "run_id=run-1"
    root.mkdir(parents=True)
    summary = root / "alternative_summary.parquet"
    report = root / "alternative_analysis_report.html"
    summary.touch()
    report.touch()
    metadata = {"run_id": "run-1", "schema_version": "v0.4.0"}
    (root / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(pipeline, "ALTERNATIVE_RESULTS_ROOT", tmp_path)

    result = pipeline.verify_run_manifest(
        {
            **metadata,
            "summary_path": str(summary),
            "report_path": str(report),
        }
    )

    assert result["run_root"] == str(root.resolve())
    assert result["run_metadata"] == metadata


def test_portfolio_analysis_publishes_matching_insurance(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "physical" / "schema_version=v0.4.0" / "run_id=physical"
    annual = root / "annual_alternative_analysis" / "year=2026"
    annual.mkdir(parents=True)
    summary = root / "alternative_summary.parquet"
    report = root / "alternative_analysis_report.html"
    summary.touch()
    report.touch()
    metadata = {"run_id": "physical", "schema_version": "v0.4.0"}
    (root / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    pl.DataFrame({
        "asset_id": ["A"] * 4, "year": [2026] * 4,
        "scenario_id": ["BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE"],
        "annual_repair_cost_usd": [150.] * 4,
    }).write_parquet(annual / "part-00000.parquet")
    source = pl.DataFrame({
        "asset_id": ["A"], "policy_id": ["P"], "insured_value": [500.],
        "deductible_amount": [50.], "deductible_type": ["standard"],
        "peril": ["wind"], "current_premium": [200.],
    })
    artifact = tmp_path / "assets.parquet"
    source.select("asset_id").write_parquet(artifact)
    workbook = tmp_path / "selected.xlsx"
    workbook.write_bytes(b"selected workbook identity")
    monkeypatch.setattr(pipeline, "ALTERNATIVE_RESULTS_ROOT", tmp_path / "physical")
    monkeypatch.setattr(pipeline, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(pipeline, "build_economics_asset_features", lambda *_: {"output_path": str(artifact)})
    monkeypatch.setattr(pipeline, "build_asset_scoped_damage", lambda *_: {"asset_results_path": str(artifact)})
    config = pipeline.load_economics_config()

    def run_alternatives(assets, selected_config, *args, **kwargs):
        assert selected_config is config
        return {**metadata, "summary_path": str(summary), "report_path": str(report)}

    def selected_portfolio(path):
        assert path == workbook
        return SimpleNamespace(source=source)

    monkeypatch.setattr(pipeline, "run_alternative_analysis_pipeline", run_alternatives)
    monkeypatch.setattr(pipeline, "validate_portfolio", selected_portfolio)
    stages = []
    result = pipeline.run_portfolio_analysis(
        workbook, tmp_path / "work", lambda stage, _: stages.append(stage), config=config,
    )

    assert result["run_id"] == "physical"
    insurance = result["insurance_run"]
    assert insurance["physical_run_id"] == result["run_id"]
    assert insurance["selected_workbook_sha256"] == pipeline.sha256_file(workbook)
    payouts = pl.read_parquet(Path(insurance["run_root"]) / "annual_insurance/year=2026/*.parquet")
    assert payouts["expected_payout_usd"].to_list() == [100.] * 4
    assert stages == ["assets", "damage", "alternatives", "insurance"]