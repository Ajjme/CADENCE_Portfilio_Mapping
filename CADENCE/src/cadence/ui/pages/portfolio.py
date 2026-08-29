"""Asset Portfolio page."""

import hashlib
import json
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.ui.components import render_asset_map, render_summary_card
from cadence.ui.paths import DEFAULT_WORKBOOK, ECONOMICS_CONFIG, UI_WORK_ROOT
from cadence.ui.pipeline import load_economics_config, run_portfolio_analysis
from cadence.ui.state import update_analysis_identity, update_source_identity
from cadence.ui.theme import page_header, section_header
from cadence.ui.workbooks import (
    analysis_identity,
    materialize_filtered_workbook,
    save_uploaded_workbook,
    sha256_file,
    validate_portfolio,
)


@st.cache_data(show_spinner=False)
def _load_portfolio(path: str, checksum: str) -> pd.DataFrame:
    del checksum
    return validate_portfolio(Path(path)).display.to_pandas()


def render() -> None:
    """Render the portfolio workflow."""
    st.markdown(
        page_header(
            "CADENCE Interactive Asset Mapping Interface",
            "Roofing Asset Portfolio · Vulnerability · Lifecycle Analysis",
        ),
        unsafe_allow_html=True,
    )
    source_path, source_checksum, source_label = _portfolio_source()
    update_source_identity(st.session_state, source_checksum)
    st.session_state["portfolio_source_path"] = str(source_path)

    try:
        assets = _load_portfolio(str(source_path), source_checksum)
    except (ValueError, OSError) as error:
        st.error(f"Portfolio validation failed: {error}")
        return
    st.success(f"Validated {len(assets):,} assets from {source_label}.")

    filter_column, map_column, summary_column = st.columns(
        [1.15, 3.35, 1.2], gap="large"
    )
    with filter_column:
        st.markdown(section_header("Filter Assets"), unsafe_allow_html=True)
        filtered = _filter_assets(assets, source_checksum)
        st.caption(f"Showing {len(filtered):,} of {len(assets):,} assets")

    selected_ids = filtered["asset_id"].astype(str).tolist()
    identity = analysis_identity(source_checksum, selected_ids)
    update_analysis_identity(st.session_state, identity)
    st.session_state["selected_asset_ids"] = selected_ids

    with summary_column:
        st.markdown(section_header("Portfolio Summary"), unsafe_allow_html=True)
        st.caption("Based on active filters")
        _render_summary(filtered)

    with map_column:
        st.markdown("#### Asset Map")
        render_asset_map(filtered, key=f"portfolio-map-{identity[:12]}")
        st.markdown("#### Processed Asset Registry")
        if filtered.empty:
            st.info("Adjust the filters to display registry records.")
        else:
            st.dataframe(
                _registry_frame(filtered),
                width="stretch",
                hide_index=True,
            )

    st.divider()
    _render_run_panel(source_path, source_checksum, selected_ids, identity)


def _portfolio_source() -> tuple[Path, str, str]:
    st.markdown("#### Upload Asset Registry")
    upload = st.file_uploader(
        "Upload the complete CADENCE Excel asset workbook",
        type=["xlsx"],
        help="The asset records must be in Sheet1. Validation/reference sheets are not read as assets.",
    )
    if upload is None:
        st.info(f"Using the repository default: {DEFAULT_WORKBOOK.relative_to(DEFAULT_WORKBOOK.parents[2])}")
        return DEFAULT_WORKBOOK, sha256_file(DEFAULT_WORKBOOK), "repository default workbook"
    payload = upload.getvalue()
    checksum = hashlib.sha256(payload).hexdigest()
    session_root = _session_root()
    path = session_root / "uploads" / f"{checksum}.xlsx"
    if not path.exists():
        save_uploaded_workbook(BytesIO(payload), path)
    return path, checksum, upload.name


def _filter_assets(assets: pd.DataFrame, checksum: str) -> pd.DataFrame:
    material_options = sorted(assets["official_material"].dropna().unique())
    selected_materials = st.multiselect(
        "Current Roof Type",
        material_options,
        default=material_options,
        key=f"materials-{checksum}",
    )
    age_range = _range_filter("Roof Age", assets["roof_age"], checksum)
    area_range = _range_filter("Roof Area", assets["roof_area_sqft"], checksum)
    terrain_column = "Terrain" if "Terrain" in assets else "terrain_label"
    terrain_options = sorted(assets[terrain_column].dropna().astype(str).unique())
    selected_terrain = st.multiselect(
        "Terrain",
        terrain_options,
        default=terrain_options,
        key=f"terrain-{checksum}",
    )
    search = st.text_input("Asset ID", key=f"asset-search-{checksum}").strip()
    mask = (
        assets["official_material"].isin(selected_materials)
        & pd.to_numeric(assets["roof_age"]).between(*age_range)
        & pd.to_numeric(assets["roof_area_sqft"]).between(*area_range)
        & assets[terrain_column].astype(str).isin(selected_terrain)
    )
    if search:
        mask &= assets["asset_id"].astype(str).str.contains(search, case=False, regex=False)
    return assets.loc[mask].copy()


def _range_filter(label: str, series: pd.Series, checksum: str) -> tuple[float, float]:
    numeric = pd.to_numeric(series, errors="coerce")
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if minimum == maximum:
        st.caption(f"{label}: {minimum:,.0f}")
        return minimum, maximum
    return st.slider(
        label,
        min_value=minimum,
        max_value=maximum,
        value=(minimum, maximum),
        key=f"{label}-{checksum}",
    )


def _render_summary(filtered: pd.DataFrame) -> None:
    render_summary_card("Total Assets", f"{len(filtered):,}")
    if filtered.empty:
        for label in ("Average Roof Age", "Total Roof Area", "Average Roof Area"):
            render_summary_card(label, "--")
    else:
        render_summary_card("Average Roof Age", f"{filtered['roof_age'].mean():,.1f} yrs")
        render_summary_card("Total Roof Area", f"{filtered['roof_area_sqft'].sum():,.0f} sq ft")
        render_summary_card("Average Roof Area", f"{filtered['roof_area_sqft'].mean():,.0f} sq ft")
    if "insured_value" in filtered and not filtered.empty:
        insured = pd.to_numeric(filtered["insured_value"], errors="coerce")
        value = f"${insured.sum():,.0f}" if insured.notna().all() else "Incomplete"
        render_summary_card("Total Insured Value", value)
    for material in ("Asphalt", "Metal", "Tile"):
        count = int((filtered["official_material"] == material).sum()) if not filtered.empty else 0
        render_summary_card(f"{material} Assets", f"{count:,}")


def _registry_frame(filtered: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "asset_id", "current_roof_type", "official_material", "subtype", "roof_age",
        "install_year", "roof_area_sqft", "Terrain", "Terrain_numeric", "latitude",
        "longitude", "insured_value", "policy_id", "peril",
    ]
    columns = [column for column in preferred if column in filtered]
    labels = {
        "asset_id": "Asset ID", "current_roof_type": "Source Roof Type",
        "official_material": "Official Material", "subtype": "Subtype",
        "roof_age": "Roof Age", "install_year": "Installation Year",
        "roof_area_sqft": "Roof Area (sq ft)", "Terrain": "Terrain",
        "Terrain_numeric": "Terrain ID", "latitude": "Latitude",
        "longitude": "Longitude", "insured_value": "Insured Value",
        "policy_id": "Policy ID", "peril": "Peril",
    }
    return filtered.loc[:, columns].rename(columns=labels).sort_values("Asset ID")


def _render_run_panel(
    source_path: Path,
    source_checksum: str,
    selected_ids: list[str],
    identity: str,
) -> None:
    st.markdown(section_header("Run CADENCE Alternative Analysis"), unsafe_allow_html=True)
    config = load_economics_config()
    with st.expander("Fixed economics configuration and provenance"):
        st.code(str(ECONOMICS_CONFIG), language=None)
        st.json(
            {
                "sha256": sha256_file(ECONOMICS_CONFIG),
                "analysis_years": [config.start_year, config.end_year],
                "real_discount_rate": config.real_discount_rate,
                "enabled_cost_streams": sorted(stream.value for stream in config.enabled_cost_streams),
                "selected_asset_count": len(selected_ids),
                "source_workbook_sha256": source_checksum,
                "filtered_portfolio_identity": identity,
            }
        )
    if not selected_ids:
        st.warning("Select at least one asset before running the analysis.")
        return
    if st.button(
        "Run Alternative Analysis",
        type="primary",
        use_container_width=True,
    ):
        run_root = _session_root() / "analyses" / identity
        derived = materialize_filtered_workbook(
            source_path, run_root / "selected_assets.xlsx", selected_ids
        )
        with st.status("Running CADENCE", expanded=True) as status:
            stage_line = st.empty()

            def progress(stage: str, message: str) -> None:
                stage_line.markdown(f"**{stage.title()}** · {message}")

            try:
                run_state = run_portfolio_analysis(derived, run_root, progress)
            except Exception as error:
                status.update(label="CADENCE analysis failed", state="error")
                st.error(str(error))
                return
            run_state.update(
                {
                    "portfolio_identity": identity,
                    "portfolio_checksum": source_checksum,
                    "uploaded_workbook_path": str(source_path),
                    "derived_workbook_path": str(derived),
                    "derived_workbook_checksum": sha256_file(derived),
                    "selected_asset_ids": selected_ids,
                }
            )
            st.session_state["run_state"] = run_state
            status.update(label="CADENCE analysis complete", state="complete")
        st.success(
            f"Run `{run_state['run_id']}` completed. Open Alternative Analysis Results from the navigation."
        )
    active = st.session_state.get("run_state")
    if active and active.get("portfolio_identity") == identity:
        st.info(
            f"Active run: `{active['run_id']}` · schema `{active['schema_version']}` · "
            f"{len(active['selected_asset_ids']):,} assets"
        )


def _session_root() -> Path:
    if "ui_session_id" not in st.session_state:
        st.session_state["ui_session_id"] = uuid.uuid4().hex
    return UI_WORK_ROOT / st.session_state["ui_session_id"]