"""Alternative Analysis Results page through the Alternative Summary stage."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.economics.market_pipeline import run_market_study
from cadence.ui.charts import (
    COST_COMPONENTS,
    MATERIAL_NAMES,
    comparison_figure,
    cost_allocation_figure,
    market_cost_figure,
    market_share_figure,
    scenario_labels,
    time_series_figure,
    wind_return_period_figure,
)
from cadence.ui.components import render_summary_card
from cadence.ui.market_data import find_study, load_study
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT
from cadence.ui.results_data import (
    METRICS,
    MAP_METRICS,
    MAP_REGIONS,
    PORTFOLIO_OPTION,
    asset_options,
    cost_allocations,
    discover_runs,
    load_asset_series,
    load_year_cost_rows,
    load_current_materials,
    load_map_geography,
    load_portfolio_series,
    load_run_metadata,
    load_summary,
    load_wind_return_periods,
    material_mix_label,
    map_outcomes,
    portfolio_summary,
    regional_map_outcomes,
)
from cadence.ui.results_map import load_map_boundaries, render_results_map
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

    asset_ids = list(summary["asset_id"].astype(str).unique())
    selected_asset = st.selectbox(
        "Asset",
        asset_options(asset_ids),
        index=0,
        format_func=lambda option: (
            f"Portfolio (all {len(asset_ids):,} assets)"
            if option == PORTFOLIO_OPTION else option
        ),
        key=f"results_asset_{metadata['run_id']}",
    )
    st.caption(
        f"Run `{metadata['run_id']}` · schema `{metadata['schema_version']}` · "
        f"{metadata['asset_count']:,} assets · Real 2026 USD"
    )

    overview_tab, time_tab, summary_tab, cost_tab, wind_tab, study_tab, run_tab = st.tabs(
        ["Overview", "Time Series", "Alternative Summary", "Cost Allocations", "Wind Return Period", "Market Study", "Run Information"]
    )
    with overview_tab:
        _render_overview(run_root, summary, selected_asset)
    with time_tab:
        _render_time_series(run_root, selected_asset)
    with summary_tab:
        _render_alternative_summary(summary, selected_asset)
    with cost_tab:
        _render_cost_allocations(run_root, selected_asset, metadata)
    with wind_tab:
        _render_wind_return_period(run_root, selected_asset, metadata)
    with study_tab:
        _render_market_study(run_root, selected_asset)
    with run_tab:
        _render_run_information(metadata, run_root)


def _render_market_study(run_root: str, selected_asset: str) -> None:
    st.warning(
        "Experimental study: not a calibrated market forecast. Disposal/carbon costs "
        "after material changes remain unverified; do not rely on these projections "
        "for investment decisions."
    )
    if selected_asset != PORTFOLIO_OPTION:
        st.info("Select Portfolio to view the Market Study.")
        return
    active = st.session_state.get("run_state")
    if not isinstance(active, dict) or Path(str(active.get("run_root", ""))).resolve() != Path(run_root).resolve():
        st.info("Market Study requires the matching active session run and its saved asset inputs.")
        return
    st.markdown(section_header("Market Study"), unsafe_allow_html=True)
    st.caption("Deterministic portfolio scenario · start-of-year replacements · projected roof stock, not calibrated market adoption")
    if st.button("Run Market Study", type="primary", key=f"run_market_study_{active['run_id']}"):
        with st.spinner("Evaluating annual roof replacement choices"):
            try:
                result = run_market_study(run_root, active)
                st.success(f"Study {result['run_id']} · {'cached' if result['cache_hit'] else 'complete'}")
            except (ValueError, OSError, KeyError) as error:
                st.error(f"Market Study unavailable: {error}")
                return
    try:
        study_root = find_study(run_root, active)
        if study_root is None:
            st.info("Run the Market Study to publish annual roof-stock and cost results.")
            return
        manifest, stock, costs, decisions = load_study(study_root, run_root)
    except (ValueError, OSError, KeyError) as error:
        st.warning(f"Saved Market Study cannot be opened: {error}")
        return
    streams = ", ".join(sorted(manifest["run_config"]["enabled_cost_streams"]))
    st.caption(f"Run {manifest['run_id']} · {streams} · real 2026 USD"
               + (" · Tile uses provisional Metal proxy" if manifest.get("temporary_tile_policy") else ""))
    if costs["unknown_count"].max():
        st.warning("Assets with incomplete required costs or damage are counted as Unknown. Affected dollar totals are unavailable.")
    st.plotly_chart(market_share_figure(stock), config={"displaylogo": False, "responsive": True})
    st.plotly_chart(market_cost_figure(costs), config={"displaylogo": False, "responsive": True})
    with st.expander("Replacement decisions"):
        if decisions.empty:
            st.info("No roofs were replaced during the selected years.")
        else:
            st.dataframe(decisions, width="stretch", hide_index=True)


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
    if asset_id == PORTFOLIO_OPTION:
        _render_portfolio_overview(run_root, summary)
        return
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
            _render_outcome_cards(row)
            st.caption(f"Cost source: {row['active_cost_source']}")
            if row["active_cost_fallback_applied"]:
                st.warning("Installed-cost fallback applied.")
            _completeness_warning(pd.DataFrame([row]))
    st.plotly_chart(
        comparison_figure(selected, f"{asset_id} NPV by alternative"),
        config={"displaylogo": False, "responsive": True},
    )


def _render_portfolio_overview(run_root: str, summary: pd.DataFrame) -> None:
    label = material_mix_label(load_current_materials(run_root))
    st.markdown(section_header(label), unsafe_allow_html=True)
    portfolio = portfolio_summary(summary)
    labels = scenario_labels(None, portfolio=True)
    columns = st.columns(3, gap="large")
    for column, scenario in zip(columns, ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE")):
        row = portfolio.loc[portfolio["scenario_id"] == scenario].iloc[0]
        with column:
            st.markdown(f"#### {labels[scenario]}")
            _render_outcome_cards(row)
            st.caption(f"Assets: {int(row['asset_count']):,}")
            if row["active_cost_fallback_applied"]:
                st.warning("Installed-cost fallback applied to one or more assets.")
            _completeness_warning(pd.DataFrame([row]))
    st.plotly_chart(
        comparison_figure(portfolio, "Portfolio NPV by alternative"),
        config={"displaylogo": False, "responsive": True},
    )
    _render_portfolio_maps(run_root, summary)


def _render_portfolio_maps(run_root: str, summary: pd.DataFrame) -> None:
    st.markdown(section_header("Replacement Opportunities"), unsafe_allow_html=True)
    try:
        geography = load_map_geography(run_root)
    except (ValueError, OSError) as error:
        st.warning(f"Opportunity maps are unavailable: {error}")
        return
    for tab, (metric, label) in zip(st.tabs(list(MAP_METRICS.values())), MAP_METRICS.items()):
        with tab:
            prefix = f"map_{Path(run_root).name}_{metric}"
            choices = {"BEST": "Best replacement", "NEW_ASPHALT": "New asphalt", "NEW_METAL": "New metal", "NEW_TILE": "New tile"}
            controls = st.columns(3)
            scenario = controls[0].selectbox("Replacement", list(choices), format_func=choices.get, key=f"{prefix}_scenario")
            region = controls[1].selectbox("Geography", ["Asset", *MAP_REGIONS], key=f"{prefix}_region")
            average = controls[2].selectbox("Aggregation", ["Total", "Average per asset"], disabled=region == "Asset", key=f"{prefix}_aggregate") == "Average per asset"
            try:
                rows = map_outcomes(summary, geography, metric, scenario)
                regions = boundaries = None
                values = rows[metric]
                if region != "Asset":
                    regions = regional_map_outcomes(rows, metric, region, average)
                    missing_ids = int(rows[MAP_REGIONS[region]].isna().sum())
                    if missing_ids:
                        st.warning(f"{missing_ids:,} assets have no {region} identifier.")
                    bounds = (float(rows.longitude.min()), float(rows.latitude.min()), float(rows.longitude.max()), float(rows.latitude.max()))
                    boundaries = load_map_boundaries(region, tuple(regions[MAP_REGIONS[region]].astype(str)), bounds)
                    values = regions["value"]
                domain = float(values.abs().max()) if values.notna().any() else 1.0
                render_results_map(rows, metric, label, prefix, domain, regions, boundaries, region)
            except (ValueError, OSError) as error:
                st.warning(f"Opportunity map is unavailable: {error}")


def _render_outcome_cards(row: pd.Series) -> None:
    render_summary_card("Final NPV", _currency(row["net_present_value_usd"]))
    render_summary_card("Cumulative Avoided Damage", _currency(row["cumulative_avoided_damage_usd"]))
    render_summary_card("Discounted Avoided Damage", _currency(row["cumulative_discounted_avoided_damage_usd"]))
    render_summary_card("Cumulative Net Benefit", _currency(row["cumulative_net_benefit_usd"]))
    render_summary_card("Burnout Replacements", f"{int(row['burnout_replacement_count']):,}")


def _render_time_series(run_root: str, asset_id: str) -> None:
    metric = st.selectbox(
        "Metric",
        list(METRICS),
        format_func=METRICS.get,
    )
    if asset_id == PORTFOLIO_OPTION:
        portfolio = load_portfolio_series(run_root, metric)
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
        return
    asset = load_asset_series(run_root, asset_id, metric)
    current_id = str(asset["official_current_material_id"].dropna().iloc[0])
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


def _render_alternative_summary(summary: pd.DataFrame, asset_id: str) -> None:
    if asset_id != PORTFOLIO_OPTION:
        selected = summary.loc[summary["asset_id"] == asset_id]
        st.markdown(section_header(f"{asset_id} Alternative Summary"), unsafe_allow_html=True)
        _completeness_warning(selected)
        st.plotly_chart(
            comparison_figure(selected, f"{asset_id} final NPV"),
            config={"displaylogo": False, "responsive": True},
        )
        st.dataframe(_display_summary(selected), width="stretch", hide_index=True)
        return
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


def _render_cost_allocations(run_root: str, asset_id: str, metadata: dict) -> None:
    config = metadata["run_config"]
    year = st.selectbox(
        "Cost year", range(int(config["start_year"]), int(config["end_year"]) + 1),
        key=f"results_cost_year_{metadata['run_id']}",
    )
    try:
        rows = load_year_cost_rows(run_root, year, asset_id)
        portfolio = asset_id == PORTFOLIO_OPTION
        costs = cost_allocations(rows, metadata, portfolio)
    except (ValueError, OSError, KeyError) as error:
        st.warning(f"Cost allocations are unavailable: {error}")
        return
    current_material = None if portfolio else str(rows["official_current_material_id"].iloc[0])
    labels = scenario_labels(current_material, portfolio=portfolio)
    title = f"{'Portfolio' if portfolio else asset_id} · {year} cost allocations"
    st.markdown(section_header(title), unsafe_allow_html=True)
    if costs["total_usd"].isna().any():
        st.warning("Some enabled costs are unavailable. Incomplete bars show known components only; their totals are unavailable.")
    if costs["allocation_estimated"].any():
        st.caption("Material/labor is allocated from effective installed cost using source shares or configured fallback shares. Tile inherits Metal shares under the temporary Tile policy.")
    st.plotly_chart(
        cost_allocation_figure(costs, title, labels),
        config={"displaylogo": False, "responsive": True},
    )
    display = costs.set_index("scenario_id").reindex(labels).reset_index()
    display["scenario_id"] = display["scenario_id"].map(labels)
    st.dataframe(
        display.rename(columns={**COST_COMPONENTS, "scenario_id": "Scenario", "total_usd": "Total"})[
            ["Scenario", *COST_COMPONENTS.values(), "Total"]
        ],
        width="stretch", hide_index=True,
    )
    st.caption("Real 2026 USD · Installation, disposal, and carbon occur on installation/replacement events; repair and loss of use are annual expected costs.")


def _render_wind_return_period(run_root: str, asset_id: str, metadata: dict) -> None:
    config = metadata["run_config"]
    years = [None, *range(int(config["start_year"]), int(config["end_year"]) + 1)]
    selected_year = st.selectbox(
        "Wind year", years, format_func=lambda year: "Baseline" if year is None else str(year),
        key=f"results_wind_year_{metadata['run_id']}",
    )
    try:
        gusts = load_wind_return_periods(run_root, asset_id, selected_year)
    except (ValueError, OSError) as error:
        st.warning(f"Wind return-period results are unavailable: {error}")
        return
    label = "Portfolio" if asset_id == PORTFOLIO_OPTION else asset_id
    period = "Baseline" if selected_year is None else str(selected_year)
    st.plotly_chart(
        wind_return_period_figure(gusts, f"{label} · {period} wind return periods"),
        config={"displaylogo": False, "responsive": True},
    )


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