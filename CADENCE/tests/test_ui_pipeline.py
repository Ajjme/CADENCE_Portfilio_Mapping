import json
from pathlib import Path

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