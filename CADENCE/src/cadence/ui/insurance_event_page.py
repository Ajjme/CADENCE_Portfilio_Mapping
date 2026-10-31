"""Controls and presentation for committed, insurance-only wind events."""

from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import polars as pl
import streamlit as st
from branca.colormap import LinearColormap
from streamlit_folium import st_folium

from cadence.insurance.event_analysis import (
    EVENT_METRICS, EVENT_PERIODS, LIMITATIONS, EventSettings, summarize_event,
)
from cadence.insurance.event_pipeline import discover_events, load_event
from cadence.reference_data.economics_assets import FIPS_TO_STATE
from cadence.ui.charts import SCENARIO_ORDER, scenario_labels
from cadence.ui.insurance_charts import event_comparison_figure
from cadence.ui.insurance_event_data import EVENT_ROOT, run_event
from cadence.ui.results_data import PORTFOLIO_OPTION, asset_options
from cadence.ui.results_map import BASE_TILES

METRIC_LABELS = dict(zip(EVENT_METRICS, ("Gross event damage", "Insured event payout")))


def render_event(run_root: str, metadata: dict) -> None:
    st.caption("Assume one local wind-return-level event occurs. No annual-probability weighting.")
    st.info(LIMITATIONS)
    runs = {item["run_id"]: item for item in discover_events(EVENT_ROOT, metadata["run_id"])}
    saved = st.selectbox(
        "Saved event run", list(runs), index=None, placeholder="Create a new event simulation",
        format_func=lambda value: (
            f"{value[:10]} · {runs[value]['settings']['year']} · "
            f"{runs[value]['settings']['return_period']}-year wind"
        ), key=f"event_saved_{metadata['run_id']}",
    )
    committed_key = f"insurance_event_committed_{metadata['run_id']}"
    settings = None
    if saved is None:
        year_col, period_col = st.columns(2)
        with year_col:
            year = st.selectbox(
                "Event year", range(int(metadata["year_start"]), int(metadata["year_end"]) + 1),
                key=f"event_year_{metadata['run_id']}",
            )
        with period_col:
            period = st.selectbox(
                "Wind return period", EVENT_PERIODS,
                format_func=lambda value: f"{value}-year" + (" (estimated)" if value == 300 else ""),
                key=f"event_period_{metadata['run_id']}",
            )
        footprint = st.radio(
            "Event footprint", ["All portfolio", "Selected states"], horizontal=True,
            key=f"event_footprint_{metadata['run_id']}",
        )
        states = st.multiselect(
            "Affected states", sorted(set(FIPS_TO_STATE.values())),
            key=f"event_states_{metadata['run_id']}",
        ) if footprint == "Selected states" else None
        ready = states is None or bool(states)
        if not ready:
            st.warning("Select at least one state, or choose All portfolio.")
        else:
            settings = EventSettings(year=year, return_period=period, states=tuple(states) if states is not None else None)
        if st.button("Run event simulation", type="primary", disabled=not ready) and settings is not None:
            st.session_state.pop(committed_key, None)
            try:
                with st.spinner("Calculating and saving the wind event..."):
                    result = run_event(run_root, settings)
                st.session_state[committed_key] = result["run_root"]
            except (ValueError, OSError, pl.exceptions.PolarsError) as error:
                st.error(f"Event simulation could not be completed: {error}")
                return
        result_root = st.session_state.get(committed_key)
        if result_root is None:
            st.info("Choose event inputs and click Run event simulation. Annualized losses remain available in the other mode.")
            return
    else:
        result_root = runs[saved]["run_root"]
    try:
        event, rows = load_event(Path(result_root), EVENT_ROOT)
    except (ValueError, OSError, pl.exceptions.PolarsError) as error:
        st.error(f"Saved event cannot be opened: {error}")
        return
    if saved is None and (settings is None or event["settings"] != settings.model_dump(mode="json")):
        st.info("Event inputs changed. Run event simulation again; previous results are not shown for these inputs.")
        return
    _render_results(event, rows)


def _render_results(event: dict, rows: pl.DataFrame) -> None:
    settings = event["settings"]
    footprint = ", ".join(settings["states"]) if settings["states"] is not None else "All portfolio"
    st.subheader(f"Committed event: {settings['year']} · {settings['return_period']}-year wind")
    st.caption(
        f"Footprint: {footprint} · event {event['run_id']} · "
        f"physical {event['physical_run_id']} · insurance {event['insurance_run_id']} · real 2026 USD"
    )
    labels = scenario_labels(None, portfolio=True)
    labels["BASELINE_CURRENT"] = "Current roof (modeled lifecycle)"
    asset_col, roof_col = st.columns(2)
    with asset_col:
        asset = st.selectbox(
            "Event asset", asset_options(rows["asset_id"].unique().sort().to_list()),
            format_func=lambda value: "Portfolio" if value == PORTFOLIO_OPTION else value,
            key=f"event_asset_{event['run_id']}",
        )
    with roof_col:
        roof = st.selectbox(
            "Event roof option", SCENARIO_ORDER, format_func=lambda value: labels[value],
            key=f"event_roof_{event['run_id']}",
        )
    view = rows if asset == PORTFOLIO_OPTION else rows.filter(pl.col("asset_id") == asset)
    selected = view.filter(pl.col("scenario_id") == roof)
    summary = summarize_event(selected).row(0, named=True)
    cards = st.columns(3)
    for column, metric in zip(cards, EVENT_METRICS):
        column.metric(METRIC_LABELS[metric], _money(summary[metric]))
        missing = summary[f"{metric}_missing_count"]
        if missing:
            column.warning(f"Total unavailable: {missing} affected asset(s) incomplete.")
    cards[2].metric("Affected / total assets", f"{summary['affected_count']} / {summary['asset_count']}")
    st.caption("Gross = event damage ratio × full installed roof cost. Payout = min(max(gross − deductible, 0), insured value), independently per asset.")
    frame = selected.to_pandas()
    st.subheader("Per-asset event results")
    st.dataframe(frame[[
        "asset_id", "state_code", "affected", "local_gust_mph", "event_damage_ratio",
        "active_installed_capex_usd", *EVENT_METRICS, "physical_issue", "payout_issue",
    ]], hide_index=True, width="stretch")
    states = summarize_event(selected, by_state=True).to_pandas()
    comparison = summarize_event(view).to_pandas()
    left, right = st.columns(2)
    with left:
        st.plotly_chart(event_comparison_figure(states, "state_code", "Loss by state"),
                        config={"displaylogo": False})
        st.dataframe(states, hide_index=True, width="stretch")
    with right:
        comparison["roof_option"] = comparison["scenario_id"].map(lambda value: labels[str(value)])
        st.plotly_chart(event_comparison_figure(comparison, "roof_option", "Independent roof alternatives"),
                        config={"displaylogo": False})
        st.dataframe(comparison, hide_index=True, width="stretch")
    metric = st.radio("Event map metric", EVENT_METRICS, format_func=lambda value: METRIC_LABELS[value],
                      horizontal=True, key=f"event_map_metric_{event['run_id']}")
    render_event_map(frame, metric, f"event_map_{event['run_id']}_{roof}_{asset}_{metric}")
    st.subheader("Download committed simulation")
    st.caption("Downloads include the entire simulated portfolio and all four roof options, not just the current display filters. JSON contains the full assumptions and source checksums.")
    export_fields = [
        pl.lit(event["run_id"]).alias("event_run_id"),
        pl.lit(settings["year"]).alias("event_year"),
        pl.lit(settings["return_period"]).alias("event_return_period"),
        pl.lit(footprint).alias("event_footprint"),
        pl.lit("real_2026_usd").alias("dollar_basis"),
        pl.lit(LIMITATIONS).alias("model_limitations"),
    ]
    for name, export in (
        ("assets", rows), ("states", summarize_event(rows, by_state=True)),
        ("portfolio_roofs", summarize_event(rows)),
    ):
        st.download_button(
            f"Download event {name.replace('_', ' ')} CSV",
            export.with_columns(*export_fields).write_csv(),
            file_name=f"event_{event['run_id']}_{name}.csv", mime="text/csv",
            key=f"download_event_{name}_{event['run_id']}",
        )
    st.download_button(
        "Download event assumptions JSON", json.dumps(event, indent=2, sort_keys=True),
        file_name=f"event_{event['run_id']}_assumptions.json", mime="application/json",
    )
    with st.expander("Event assumptions and provenance"):
        st.json(event)


def _money(value: float | None) -> str:
    return "Unavailable" if value is None or not math.isfinite(value) else f"${value:,.0f}"


def build_event_map(rows: pd.DataFrame, metric: str) -> tuple[folium.Map | None, int]:
    if metric not in EVENT_METRICS:
        raise ValueError("unsupported event map metric")
    valid = (
        np.isfinite(rows["latitude"]) & np.isfinite(rows["longitude"])
        & rows["latitude"].between(-90, 90) & rows["longitude"].between(-180, 180)
    )
    points = rows.loc[valid]
    omitted = len(rows) - len(points)
    if points.empty:
        return None, omitted
    maximum = max(1.0, float(points[metric].max())) if points[metric].notna().any() else 1.0
    palette = LinearColormap(["#fff2cc", "#e58b38", "#a51f2a"], vmin=0, vmax=maximum)
    palette.caption = f"{METRIC_LABELS[metric]} · real 2026 USD"
    event_map = folium.Map(location=[points["latitude"].mean(), points["longitude"].mean()],
                           zoom_start=5, tiles=BASE_TILES, attr="Tiles &copy; Esri")
    for row in points.to_dict("records"):
        color = "#376b91" if not row["affected"] else (
            "#80858c" if pd.isna(row[metric]) else palette(row[metric])
        )
        status = "Affected" if row["affected"] else "Unaffected"
        gust = "Unavailable" if pd.isna(row["local_gust_mph"]) else f"{row['local_gust_mph']:.1f} mph"
        damage = "Unavailable" if pd.isna(row["event_damage_ratio"]) else f"{row['event_damage_ratio']:.1%}"
        details = (
            f"<b>{escape(str(row['asset_id']))}</b><br>State: {escape(str(row['state_code']))}"
            f"<br>{status}<br>Local return-level gust: {gust}<br>Event damage: {damage}"
            f"<br>Gross: {_money(row[EVENT_METRICS[0]])}<br>Payout: {_money(row[EVENT_METRICS[1]])}"
        )
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]], radius=8, color=color,
            fill=True, fill_color=color, fill_opacity=0.85,
            tooltip=folium.Tooltip(details), popup=folium.Popup(details, max_width=340),
        ).add_to(event_map)
    if len(points) > 1:
        event_map.fit_bounds([[points["latitude"].min(), points["longitude"].min()],
                              [points["latitude"].max(), points["longitude"].max()]], max_zoom=11)
    palette.add_to(event_map)
    return event_map, omitted


def render_event_map(rows: pd.DataFrame, metric: str, key: str) -> None:
    event_map, omitted = build_event_map(rows, metric)
    if omitted:
        st.warning(f"{omitted} asset(s) cannot be placed on the map. Their financial results remain included.")
    st.caption("Blue = unaffected; gray = unavailable; yellow-to-red = affected loss. No storm track is modeled.")
    if event_map is not None:
        st_folium(event_map, height=480, use_container_width=True, key=key, returned_objects=[])
