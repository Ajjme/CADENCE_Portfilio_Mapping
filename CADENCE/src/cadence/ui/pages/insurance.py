"""Insurance underwriting view for completed roof alternative runs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from cadence.ui.charts import SCENARIO_ORDER, scenario_labels
from cadence.ui.components import render_summary_card
from cadence.ui.insurance_charts import (
    annual_balance_figure,
    coverage_figure,
    cumulative_figure,
    loss_ratio_figure,
)
from cadence.ui.insurance_data import (
    discover_insurance_runs,
    load_insurance_issues,
    load_insurance_metadata,
    load_insurance_series,
    load_policy_snapshot,
)
from cadence.ui.results_data import PORTFOLIO_OPTION, asset_options
from cadence.ui.theme import page_header, section_header


def render() -> None:
    st.markdown(
        page_header("CADENCE Insurance View", "Projected wind-roof underwriting · 2026–2050"),
        unsafe_allow_html=True,
    )
    runs = {row["run_id"]: row for row in discover_insurance_runs() if row.get("run_id")}
    active = st.session_state.get("run_state")
    insurance_run = active.get("insurance_run") if isinstance(active, dict) else None
    active_id = insurance_run.get("run_id") if isinstance(insurance_run, dict) else None
    if active_id and active_id not in runs:
        runs[active_id] = insurance_run
    if not runs:
        st.info("No insurance policy snapshot is available. Run Alternative Analysis from Asset Portfolio to create one. Older physical-only runs remain available in Alternative Analysis Results.")
        return

    selected_id = st.selectbox(
        "Insurance run", list(runs), index=list(runs).index(active_id) if active_id in runs else None,
        placeholder="Choose a saved insurance run",
        format_func=lambda run_id: (
            f"{run_id[:10]}… · physical {runs[run_id]['physical_run_id'][:10]}… · "
            f"{runs[run_id]['asset_count']} assets"
        ),
    )
    if selected_id is None:
        st.info("Choose an insurance run. Physical-only runs without a policy snapshot cannot be displayed here.")
        return
    run_root = str(Path(runs[selected_id]["run_root"]))
    try:
        metadata = load_insurance_metadata(run_root)
        policies = load_policy_snapshot(run_root)
    except (ValueError, OSError) as error:
        st.error(f"Insurance results cannot be opened: {error}")
        return
    if policies.empty:
        st.warning("This insurance run contains no selected assets.")
        return

    labels = scenario_labels(None, portfolio=True)
    labels["BASELINE_CURRENT"] = "Current roof"
    asset_column, scenario_column, year_column = st.columns([1.6, 1.4, 0.8], gap="medium")
    with asset_column:
        asset_id = st.selectbox(
            "Asset", asset_options(policies["asset_id"].astype(str).tolist()),
            format_func=lambda item: f"Portfolio ({len(policies):,} assets)" if item == PORTFOLIO_OPTION else item,
            key=f"insurance_asset_{selected_id}",
        )
    with scenario_column:
        scenario = st.selectbox(
            "Roof option", SCENARIO_ORDER, format_func=lambda item: labels[item],
            key=f"insurance_scenario_{selected_id}",
        )
    with year_column:
        year = st.selectbox(
            "Year", range(int(metadata["year_start"]), int(metadata["year_end"]) + 1),
            key=f"insurance_year_{selected_id}",
        )
    try:
        series = load_insurance_series(run_root, asset_id)
    except (ValueError, OSError) as error:
        st.error(f"Annual insurance results cannot be opened: {error}")
        return
    selected = series.loc[series["scenario_id"] == scenario]
    current = selected.loc[selected["year"] == year]
    if current.empty:
        st.warning("No annual result is available for this selection.")
        return
    row = current.iloc[0]
    portfolio = asset_id == PORTFOLIO_OPTION
    asset_policy = policies.loc[policies["asset_id"] == asset_id] if not portfolio else None
    st.caption(
        f"Insurance run `{selected_id}` · physical run `{metadata['physical_run_id']}` · "
        "real 2026 USD · fixed annual premium per asset"
    )
    if not portfolio and asset_policy is not None and not asset_policy.empty:
        st.caption(f"Policy ID: {asset_policy.iloc[0]['policy_id'] or 'Unavailable'}")
    missing = int(row["missing_count"]) if portfolio else int(pd.notna(row["insurance_issue"]))
    if missing:
        st.warning(f"Insurance values unavailable for {missing:,} asset(s) in {year} / {labels[scenario]}.")
        if portfolio:
            st.dataframe(load_insurance_issues(run_root, int(year), scenario), hide_index=True, width="stretch")
        else:
            st.caption(str(row["insurance_issue"]))
    elif pd.isna(row["cumulative_premium_usd"]) or pd.isna(row["cumulative_payout_usd"]):
        st.info("Cumulative totals are unavailable because an earlier year has incomplete insurance results.")

    st.markdown(section_header(f"{year} · {labels[scenario]}"), unsafe_allow_html=True)
    cards = st.columns(3, gap="large")
    for column, (title, field, kind) in zip(cards, (
        ("Insured value", "insured_value", "currency"),
        ("Annual premium", "premium_usd", "currency"),
        ("Expected payout", "expected_payout_usd", "currency"),
    )):
        with column:
            render_summary_card(title, _format(row[field], kind))
    cards = st.columns(3, gap="large")
    for column, (title, field, kind) in zip(cards, (
        ("Underwriting margin", "underwriting_margin_usd", "currency"),
        ("Loss ratio", "loss_ratio", "ratio"),
        ("Break-even premium", "expected_payout_usd", "currency"),
    )):
        with column:
            render_summary_card(title, _format(row[field], kind))

    st.caption("Expected wind-roof repair payout uses an annual-loss proxy: min(max(expected repair − deductible, 0), insured value). Margin excludes expenses and other claims; it is not total insurance profit. A zero premium has an N/A loss ratio.")
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.plotly_chart(annual_balance_figure(selected, f"{labels[scenario]} · yearly cash flows"),
                        config={"displaylogo": False, "responsive": True})
    with right:
        st.plotly_chart(loss_ratio_figure(series), config={"displaylogo": False, "responsive": True})
    lower_left, lower_right = st.columns(2, gap="large")
    with lower_left:
        st.plotly_chart(cumulative_figure(selected, f"{labels[scenario]} · through {metadata['year_end']}"),
                        config={"displaylogo": False, "responsive": True})
    with lower_right:
        if not portfolio and not missing:
            st.plotly_chart(coverage_figure(row), config={"displaylogo": False, "responsive": True})
        else:
            st.markdown(section_header("Policy inventory"), unsafe_allow_html=True)
            st.dataframe(policies, hide_index=True, width="stretch")

    with st.expander("Insurance run provenance"):
        st.json(metadata)


def _format(value: object, kind: str) -> str:
    if pd.isna(value):
        return "N/A" if kind == "ratio" else "--"
    if kind == "ratio":
        return f"{float(value):.1%}"
    return f"${float(value):,.0f}"