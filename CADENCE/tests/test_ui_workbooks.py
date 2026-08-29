from pathlib import Path

from openpyxl import load_workbook

from cadence.ui.paths import DEFAULT_WORKBOOK
from cadence.ui.workbooks import (
    analysis_identity,
    materialize_filtered_workbook,
    sha256_file,
    validate_portfolio,
)


def test_default_workbook_uses_asset_sheet_and_official_materials() -> None:
    portfolio = validate_portfolio(DEFAULT_WORKBOOK)

    assert portfolio.source.height == 6
    assert set(portfolio.display["official_material"].to_list()) <= {
        "Asphalt", "Metal", "Tile"
    }
    assert "current_roof_type" in portfolio.source.columns


def test_filtered_workbook_preserves_other_sheets_and_source_columns(
    tmp_path: Path,
) -> None:
    portfolio = validate_portfolio(DEFAULT_WORKBOOK)
    selected = portfolio.display["asset_id"].head(2).to_list()
    destination = tmp_path / "selected.xlsx"

    materialize_filtered_workbook(DEFAULT_WORKBOOK, destination, selected)

    workbook = load_workbook(destination, read_only=True, data_only=True)
    assert "asset_validation_lists" in workbook.sheetnames
    assert [cell.value for cell in workbook["Sheet1"][1]] == portfolio.source.columns
    assert validate_portfolio(destination).source.height == 2


def test_analysis_identity_ignores_filter_order() -> None:
    checksum = sha256_file(DEFAULT_WORKBOOK)

    assert analysis_identity(checksum, ["A-2", "A-1"]) == analysis_identity(
        checksum, ["A-1", "A-2"]
    )