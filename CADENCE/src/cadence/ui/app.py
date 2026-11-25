"""Native multipage entry point for the CADENCE Streamlit application."""

import streamlit as st

from cadence.economics.temporary_policies import TEMPORARY_TILE_POLICY_ID
from cadence.reference_data.precomputed import download_precomputed_files
from cadence.ui import program_page
from cadence.ui.pages import insurance, portfolio, results
from cadence.ui.paths import DATA_ROOT
from cadence.ui.theme import APP_CSS


@st.cache_resource(show_spinner="Downloading reference data...")
def _precomputed_files_ready() -> list[str]:
    """Fetch any missing precomputed file from R2 once per server start, not on every page load."""
    return download_precomputed_files(DATA_ROOT)


def main() -> None:
    st.set_page_config(layout="wide", page_title="CADENCE Portfolio Analysis")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    _precomputed_files_ready()
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
            st.Page(
                insurance.render,
                title="Insurance View",
                icon=":material/shield:",
                url_path="insurance",
            ),
            st.Page(
                program_page.render,
                title="Program View",
                icon=":material/savings:",
                url_path="program",
            ),
        ]
    )
    navigation.run()


if __name__ == "__main__":
    main()