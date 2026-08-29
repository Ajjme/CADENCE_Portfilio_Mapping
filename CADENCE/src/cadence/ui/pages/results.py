"""Alternative Analysis Results page through the Alternative Summary stage."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.ui.charts import (
    MATERIAL_NAMES,
    comparison_figure,
    scenario_labels,
    time_series_figure,
)
from cadence.ui.components import render_summary_card
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT
from cadence.ui.results_data import (
    METRICS,
    discover_runs,
    load_asset_series,
    load_portfolio_series,
    load_run_metadata,
    load_summary,
    portfolio_summary,
)
from cadence.ui.theme import page_header, section_header


def render() -> None:
    """Render the results workflow."""
    st.markdown(
        page_header(
            "CADENCE Roof Alternative Analysis",
            "Avoided Damage · Economic Performance · 2026–2050",
        ),
        unsafe_allow_html=True,
    )
    run_root = _select_run()
    if run_root is None:
        st.info("Run an analysis on Asset Portfolio or explicitly select an immutable run.")
        return
    try:
        metadata = load_run_metadata(run_root)
        summary = load_summary(run_root)
    except (ValueError, OSError) as error:
        st.error(f"Results cannot be opened: {error}")
        return
    if summary.empty:
        st.warning("The selected run has no Alternative Summary rows.")
        return

    asset_ids = sorted(summary["asset_id"].astype(str).unique())
    selected_asset = st.selectbox("Asset", asset_ids)
    st.caption(
        f"Run `{metadata['run_id']}` · schema `{metadata['schema_version']}` · "
        f"{metadata['asset_count']:,} assets · Real 2026 USD"
    )

    overview_tab, time_tab, summary_tab, run_tab = st.tabs(
        ["Overview", "Time Series", "Alternative Summary", "Run Information"]
    )
    with overview_tab:
        _render_overview(run_root, summary, selected_asset)
    with time_tab:
        _render_time_series(run_root, selected_asset)
    with summary_tab:
        _render_alternative_summary(summary)
    with run_tab:
        _render_run_information(metadata, run_root)


def _select_run() -> str | None:
    active = st.session_state.get("run_state")
    active_root = active.get("run_root") if isinstance(active, dict) else None
    runs = discover_runs(str(ALTERNATIVE_RESULTS_ROOT))
    options = {row["run_id"]: row for row in runs if row.get("run_id")}
    if active_root:
        active_id = str(active.get("run_id"))
        st.success(f"Using completed session run `{active_id}`.")
        if not st.toggle("Select a different immutable run", value=False):
            return str(active_root)
    selected = st.selectbox(
        "Existing immutable run",
        list(options),
        index=None,
        placeholder="Choose a run ID",
        format_func=lambda run_id: (
            f"{run_id} · {options[run_id]['schema_version']} · "
            f"{options[run_id]['asset_count']} assets · {options[run_id]['run_timestamp']}"
        ),
    )
    return options[selected]["run_root"] if selected else None


def _render_overview(run_root: str, summary: pd.DataFrame, asset_id: str) -> None:
    annual = load_asset_series(run_root, asset_id, "net_present_value_usd")
    current_id = str(annual["official_current_material_id"].dropna().iloc[0])
    current_material = MATERIAL_NAMES.get(current_id, current_id)
    st.markdown(section_header(f"Installed roof · {current_material}"), unsafe_allow_html=True)
    selected = summary.loc[summary["asset_id"] == asset_id]
    columns = st.columns(3, gap="large")
    for column, scenario in zip(columns, ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE")):
        row = selected.loc[selected["scenario_id"] == scenario].iloc[0]
        with column:
            st.markdown(f"#### {scenario_labels(current_id)[scenario]}")
            render_summary_card("Final NPV", _currency(row["net_present_value_usd"]))
            render_summary_card("Cumulative Avoided Damage", _currency(row["cumulative_avoided_damage_usd"]))
            render_summary_card("Discounted Avoided Damage", _currency(row["cumulative_discounted_avoided_damage_usd"]))
            render_summary_card("Cumulative Net Benefit", _currency(row["cumulative_net_benefit_usd"]))
            render_summary_card("Burnout Replacements", f"{int(row['burnout_replacement_count']):,}")
            st.caption(f"Cost source: {row['active_cost_source']}")
            if row["active_cost_fallback_applied"]:
                st.warning("Installed-cost fallback applied.")
            _completeness_warning(pd.DataFrame([row]))
    portfolio = portfolio_summary(summary)
    portfolio_chart, asset_chart = st.columns(2, gap="large")
    with portfolio_chart:
        st.plotly_chart(
            comparison_figure(portfolio, "Portfolio NPV by alternative"),
            config={"displaylogo": False, "responsive": True},
        )
    with asset_chart:
        st.plotly_chart(
            comparison_figure(selected, f"{asset_id} NPV by alternative"),
            config={"displaylogo": False, "responsive": True},
        )


def _render_time_series(run_root: str, asset_id: str) -> None:
    metric = st.selectbox(
        "Metric",
        list(METRICS),
        format_func=METRICS.get,
    )
    asset = load_asset_series(run_root, asset_id, metric)
    portfolio = load_portfolio_series(run_root, metric)
    current_id = str(asset["official_current_material_id"].dropna().iloc[0])
    missing = int(portfolio["missing_value_count"].sum())
    if missing:
        st.warning(
            f"{missing:,} portfolio values are unavailable. Affected totals are shown as gaps."
        )
    st.plotly_chart(
        time_series_figure(
            portfolio,
            f"Portfolio · {METRICS[metric]}",
            scenario_labels(None, portfolio=True),
            portfolio=True,
        ),
        config={"displaylogo": False, "responsive": True},
    )
    st.plotly_chart(
        time_series_figure(
            asset,
            f"{asset_id} · {METRICS[metric]}",
            scenario_labels(current_id),
        ),
        config={"displaylogo": False, "responsive": True},
    )
    unavailable = int(asset["metric_value"].isna().sum())
    if unavailable:
        st.caption(f"{unavailable:,} selected-asset values are unavailable and shown as gaps.")


def _render_alternative_summary(summary: pd.DataFrame) -> None:
    st.markdown(section_header("Portfolio Alternative Summary"), unsafe_allow_html=True)
    portfolio = portfolio_summary(summary)
    _completeness_warning(summary)
    st.plotly_chart(
        comparison_figure(portfolio, "Portfolio final NPV"),
        config={"displaylogo": False, "responsive": True},
    )
    st.dataframe(_display_summary(portfolio), width="stretch", hide_index=True)
    st.markdown("#### Asset-level summary")
    st.dataframe(_display_summary(summary), width="stretch", hide_index=True)


def _render_run_information(metadata: dict, run_root: str) -> None:
    st.markdown(section_header("Immutable Run Provenance"), unsafe_allow_html=True)
    st.code(run_root, language=None)
    report = Path(run_root) / "alternative_analysis_report.html"
    st.caption(f"Generated HTML reference: {report}")
    st.json(metadata)


def _completeness_warning(frame: pd.DataFrame) -> None:
    labels = {
        "repair_cost_incomplete": "repair cost",
        "climate_risk_total_incomplete": "climate risk total",
        "event_cost_incomplete": "event cost",
    }
    incomplete = [
        label for column, label in labels.items()
        if column in frame and frame[column].fillna(True).any()
    ]
    if incomplete:
        st.warning("Incomplete outputs: " + ", ".join(incomplete) + ".")


def _currency(value: object) -> str:
    return "Unavailable" if pd.isna(value) else f"${float(value):,.0f}"


def _display_summary(frame: pd.DataFrame) -> pd.DataFrame:
    labels = {
        "asset_id": "Asset ID", "scenario_id": "Scenario",
        "asset_count": "Assets", "through_year": "Through Year",
        "cumulative_avoided_damage_usd": "Cumulative Avoided Damage",
        "cumulative_discounted_avoided_damage_usd": "Discounted Avoided Damage",
        "cumulative_net_benefit_usd": "Cumulative Net Benefit",
        "net_present_value_usd": "Final NPV",
        "burnout_replacement_count": "Burnout Replacements",
        "active_cost_source": "Active Cost Source",
        "active_cost_fallback_applied": "Cost Fallback",
        "repair_cost_incomplete": "Repair Cost Incomplete",
        "climate_risk_total_incomplete": "Climate Risk Incomplete",
        "event_cost_incomplete": "Event Cost Incomplete",
    }
    columns = [column for column in labels if column in frame]
    return frame.loc[:, columns].rename(columns=labels)