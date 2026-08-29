"""Native multipage entry point for the CADENCE Streamlit application."""

import streamlit as st

from cadence.economics.temporary_policies import TEMPORARY_TILE_POLICY_ID
from cadence.ui.pages import portfolio, results
from cadence.ui.theme import APP_CSS

st.set_page_config(layout="wide", page_title="CADENCE Portfolio Analysis")
st.markdown(APP_CSS, unsafe_allow_html=True)
if st.session_state.get("alternative_analysis_policy_id") != TEMPORARY_TILE_POLICY_ID:
    st.session_state.pop("run_state", None)
    st.session_state["alternative_analysis_policy_id"] = TEMPORARY_TILE_POLICY_ID

navigation = st.navigation(
    [
        st.Page(
            portfolio.render,
            title="Asset Portfolio",
            icon=":material/map:",
            url_path="portfolio",
            default=True,
        ),
        st.Page(
            results.render,
            title="Alternative Analysis Results",
            icon=":material/analytics:",
            url_path="results",
        ),
    ]
)
navigation.run()