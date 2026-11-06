"""Single-home incentive page, outside Streamlit's legacy pages discovery."""

import pandas as pd
import polars as pl
import streamlit as st

from cadence.program.contracts import COUNTERFACTUALS, TARGETS
from cadence.ui.charts import scenario_labels
from cadence.ui.components import render_summary_card
from cadence.ui.paths import ALTERNATIVE_RESULTS_ROOT
from cadence.ui.program_charts import funding_figure, funding_waterfall
from cadence.ui.program_data import create_program_run, discover_program_runs, load_program_results
from cadence.ui.results_data import discover_runs, load_run_metadata, load_summary
from cadence.ui.theme import page_header, section_header

PUBLIC_GOOD = {
    "Post-disaster demand surge": (
        "Fewer simultaneous roof repairs could reduce post-disaster pressure on labor and materials. "
        "This benefit is not quantified by the existing P90 installation-wage setting."
    ),
    "Insurer claims-paying capacity": (
        "Reduced correlated claims could improve an insurer's capacity to pay claims. "
        "No insolvency probability, capital benefit, or homeowner premium discount is modeled."
    ),
    "Financing and bond-related costs": (
        "Lower risk may affect borrowing or bond-insurance costs for governments or insurers. "
        "No rate reduction or financial benefit is estimated or guaranteed."
    ),
}
READ_ERRORS = (ValueError, OSError, KeyError, pl.exceptions.PolarsError)


def render() -> None:
    st.markdown(page_header("CADENCE Program View", "Single-home roof incentive planning"), unsafe_allow_html=True)
    st.info(
        "Pre-insurance economic proxy: full expected repair savings, not household net-of-insurance savings. "
        "A break-even grant is not a guarantee of participation or an affordability assessment."
    )
    runs = {r["run_id"]: r for r in discover_program_runs()}
    with st.expander("Create a saved Program run", expanded=not runs):
        st.caption("Uses one home's saved physical inputs. Insurance fields are not required. No portfolio budget is calculated.")
        parents = {r["run_id"]: r for r in discover_runs(str(ALTERNATIVE_RESULTS_ROOT)) if r.get("run_id")}
        active = st.session_state.get("run_state")
        active_id = active.get("run_id") if isinstance(active, dict) else None
        if not parents:
            st.info("Run Alternative Analysis from Asset Portfolio before creating Program results.")
        else:
            parent_id = st.selectbox(
                "Physical run", list(parents),
                index=list(parents).index(active_id) if active_id in parents else None,
                placeholder="Choose a physical run", key="program_parent",
            )
            if parent_id is not None:
                parent_root = parents[parent_id]["run_root"]
                try:
                    load_run_metadata(parent_root)
                    assets = sorted(load_summary(parent_root)["asset_id"].astype(str).unique())
                    if not assets:
                        st.warning("This physical run has no homes.")
                    else:
                        asset_id = st.selectbox("Home", assets, key=f"program_home_{parent_id}")
                        if st.button("Calculate Program incentives", type="primary"):
                            with st.spinner("Evaluating installation years and saving Program results"):
                                result = create_program_run(parent_root, asset_id)
                            runs[result["run_id"]] = result
                            st.session_state["program_saved_run"] = result["run_id"]
                            st.success("Program results saved." if not result["cache_hit"] else "Verified saved Program results reused.")
                except READ_ERRORS as error:
                    st.error(f"Program inputs cannot be used: {error}")
    if not runs:
        st.info("No saved Program results are available. Create a single-home Program run above.")
        _public_good()
        return
    if st.session_state.get("program_saved_run") not in runs:
        st.session_state.pop("program_saved_run", None)
    selected = st.selectbox(
        "Program run", list(runs), index=None, placeholder="Choose a saved Program run",
        key="program_saved_run",
    )
    if selected is None:
        st.info("Choose a saved Program run; the newest result is not selected automatically.")
        _public_good()
        return
    try:
        metadata, candidates, annual = load_program_results(runs[selected]["run_root"])
    except READ_ERRORS as error:
        st.error(f"Program results cannot be opened: {error}")
        return
    _results(metadata, candidates, annual)
    _public_good()
    with st.expander("Program assumptions and provenance"):
        st.caption(
            "Material/labor and enabled cash disposal costs are included. Carbon, insurance payouts, "
            "premium changes, financing, other grants, public-good values, and terminal value do not enter the grant. "
            "Expected annual losses use the existing start-of-year modeling convention."
        )
        st.json(metadata)


def _results(metadata: dict, candidates: pd.DataFrame, annual: pd.DataFrame) -> None:
    config = metadata["run_config"]
    st.caption(
        f"Home: {metadata['asset_id']} | Physical run: {metadata['parent_run_id']} | "
        f"{config['start_year']}-{config['end_year']} | real 2026 USD | "
        f"real discount rate {config['real_discount_rate']:.1%}"
    )
    st.warning("Lowest modeled incentive within this study horizon; remaining roof value is excluded.")
    st.caption(
        "Each year is a separate installation choice, not an annual grant payment. "
        "Do not add the economic grant and upfront gap, or sum across candidate years."
    )
    if metadata.get("temporary_tile_policy"):
        st.warning("Temporary Tile policy: Metal lifecycle/vulnerability with 1.2x installed and repair costs after installation. Not independently validated Tile resilience.")
    labels = scenario_labels(None)
    columns = st.columns([1, 1.8, 1])
    with columns[0]:
        target = st.selectbox("Target roof", TARGETS, format_func=labels.__getitem__, key=f"program_target_{metadata['run_id']}")
    with columns[1]:
        comparison = st.selectbox("Counterfactual", list(COUNTERFACTUALS), format_func=COUNTERFACTUALS.__getitem__,
                                  key=f"program_comparison_{metadata['run_id']}")
    roof = candidates.loc[candidates["target_scenario"] == target]
    series = roof.loc[roof["counterfactual"] == comparison]
    best = series.loc[series["recommended"]]
    years = series["candidate_year"].astype(int).tolist()
    with columns[2]:
        default_year = int(best.iloc[0]["candidate_year"]) if not best.empty else years[0]
        year = st.selectbox("Installation year", years, index=years.index(default_year),
                            key=f"program_year_{metadata['run_id']}_{target}_{comparison}")
    row = series.loc[series["candidate_year"] == year].iloc[0]
    if bool(row["same_material_renewal"]):
        st.info("Same-material roof renewal, not a different-material resilience upgrade.")
    if bool(row["recommendation_provisional"]):
        st.warning("Some candidate years are incomplete. Any best available year is provisional.")
    if pd.notna(row["unavailable_reason"]):
        st.warning(str(row["unavailable_reason"]))
    baseline = annual.loc[
        (annual["candidate_year"] == config["start_year"]) & (annual["scenario_id"] == "BASELINE_CURRENT")
    ].sort_values("year")
    replacements = baseline.loc[baseline["installation_event"], "year"]
    next_replacement = str(int(replacements.iloc[0])) if not replacements.empty else "outside this horizon"
    st.caption(f"Initial roof age: {int(baseline.iloc[0]['input_roof_age'])} years | Next conventional replacement: {next_replacement}")
    cards = st.columns(4)
    values = [
        ("Recommended year", str(int(best.iloc[0]["candidate_year"])) if not best.empty else "Unavailable"),
        ("Recommended grant", _money(best.iloc[0]["economic_grant_usd"]) if not best.empty else "--"),
        ("Selected-year grant", _money(row["economic_grant_usd"])),
        ("Selected-year upfront gap", _money(row["upfront_gap_usd"])),
    ]
    for column, (label, value) in zip(cards, values):
        with column:
            render_summary_card(label, value)
    st.plotly_chart(funding_figure(series, int(year)), config={"displaylogo": False})
    st.markdown(section_header("Compare both alternatives"), unsafe_allow_html=True)
    for column, counterfactual in zip(st.columns(2), COUNTERFACTUALS):
        selected = roof.loc[(roof["counterfactual"] == counterfactual) & (roof["candidate_year"] == year)].iloc[0]
        recommendation = roof.loc[(roof["counterfactual"] == counterfactual) & roof["recommended"]]
        with column:
            st.markdown(f"**{COUNTERFACTUALS[counterfactual]}**")
            st.write(f"Grant: {_money(selected['economic_grant_usd'])} | Upfront gap: {_money(selected['upfront_gap_usd'])}")
            st.caption(
                f"Target cash cost: {_money(selected['target_upfront_usd'])} | "
                f"Comparator cash cost: {_money(selected['comparator_upfront_usd'])} | "
                f"Signed difference: {_money(selected['signed_upfront_difference_usd'])}"
            )
            if not recommendation.empty:
                item = recommendation.iloc[0]
                st.caption(f"{'Provisional best' if item['recommendation_provisional'] else 'Recommended'}: "
                           f"{int(item['candidate_year'])} | {_money(item['economic_grant_usd'])}")
            else:
                st.caption("Recommendation unavailable.")
    if pd.notna(row["economic_grant_usd"]):
        st.plotly_chart(funding_waterfall(row), config={"displaylogo": False})
        st.caption(f"Discounted modeled repair savings: {_money(row['npv_repair_usd'])}. Negative values mean higher repair costs, not improved resilience.")
    st.markdown(section_header("Installation-choice audit"), unsafe_allow_html=True)
    st.dataframe(roof, hide_index=True, width="stretch")
    st.download_button("Download candidate comparisons (CSV)", roof.to_csv(index=False),
                       file_name=f"program-{metadata['run_id']}-{target}.csv", mime="text/csv")
    with st.expander("Annual roof states and cash flows"):
        audit = annual.loc[annual["candidate_year"] == year]
        st.caption("All four physical paths for this candidate year. Carbon is informational and excluded from Program grants.")
        st.dataframe(audit, hide_index=True, width="stretch")
        st.download_button("Download annual audit (CSV)", audit.to_csv(index=False),
                           file_name=f"program-{metadata['run_id']}-{year}-annual.csv", mime="text/csv")


def _public_good() -> None:
    st.markdown(section_header("Public-good benefits - Not yet modeled"), unsafe_allow_html=True)
    for column, (label, explanation) in zip(st.columns(3), PUBLIC_GOOD.items()):
        with column:
            if st.button(label):
                st.info(f"Not yet modeled. {explanation} No value enters the incentive estimate.")


def _money(value: object) -> str:
    return "--" if pd.isna(value) else f"${float(value):,.2f}"
