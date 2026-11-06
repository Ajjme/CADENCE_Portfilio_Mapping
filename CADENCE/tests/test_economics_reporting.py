from pathlib import Path

import polars as pl

from cadence.economics.reporting import REPORT_COLUMNS, write_alternative_analysis_report


def test_writes_self_contained_asset_selectable_report(tmp_path: Path) -> None:
    rows = []
    for asset_id in ("A-1", "A-2"):
        for scenario_id in (
            "BASELINE_CURRENT",
            "NEW_ASPHALT",
            "NEW_METAL",
            "NEW_TILE",
        ):
            row = {column: 0.0 for column in REPORT_COLUMNS}
            row.update(
                {
                    "asset_id": asset_id,
                    "year": 2026,
                    "scenario_id": scenario_id,
                    "official_current_material_id": (
                        "OFFICIAL_METAL" if asset_id == "A-1" else "OFFICIAL_ASPHALT"
                    ),
                    "installation_event": scenario_id != "BASELINE_CURRENT",
                    "burnout_replacement_event": False,
                    "annual_repair_cost_usd": 1_000.0,
                }
            )
            rows.append(row)
    output = tmp_path / "report.html"

    annual_analysis = pl.DataFrame(rows)
    write_alternative_analysis_report(annual_analysis, output)

    html = output.read_text(encoding="utf-8")
    assert "plotly.js" in html
    assert '<option value="A-1">A-1</option>' in html
    assert '<option value="A-2">A-2</option>' in html
    assert "Annual repair cost" in html
    assert 'type:"bar"' in html
    assert 'barmode:"group"' in html
    assert 'mode:"lines"' not in html
    assert "NEW_TILE" not in html
    assert "New tile" not in html
    assert annual_analysis.filter(pl.col("scenario_id") == "NEW_TILE").height == 2
    assert "Installed roof ${formatMaterial(currentMaterial)}" in html
    assert '"official_current_material_id":"OFFICIAL_METAL"' in html