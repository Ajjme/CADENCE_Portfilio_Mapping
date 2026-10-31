"""Program funding requirements, distinct from annual grant expenditure."""

import pandas as pd
import plotly.graph_objects as go


def funding_figure(candidates: pd.DataFrame, selected_year: int) -> go.Figure:
    frame = candidates.sort_values("candidate_year")
    figure = go.Figure()
    for field, title, color in (
        ("economic_grant_usd", "Economic break-even grant", "#19817d"),
        ("upfront_gap_usd", "Incremental upfront gap", "#c08b3a"),
    ):
        figure.add_scatter(
            x=frame["candidate_year"], y=frame[field], name=title, mode="lines+markers",
            connectgaps=False, line={"color": color},
            hovertemplate="Install in %{x}<br>%{y:$,.2f}<extra>%{fullData.name}</extra>",
        )
    best = frame.loc[frame["recommended"]]
    if not best.empty:
        figure.add_scatter(
            x=best["candidate_year"], y=best["economic_grant_usd"],
            mode="markers", marker={"symbol": "star", "size": 16, "color": "#19817d"},
            name="Best available (provisional)" if best["recommendation_provisional"].any() else "Recommended",
        )
    figure.add_vline(x=selected_year, line_dash="dot", line_color="#696f7b")
    figure.update_layout(
        title="One-time funding requirement by installation year",
        xaxis_title="Candidate installation year (mutually exclusive choices)",
        yaxis_title="Real 2026 USD", margin={"l": 24, "r": 24, "t": 60, "b": 40},
    )
    return figure


def funding_waterfall(row: pd.Series) -> go.Figure:
    labels = [
        "Installation-year cash difference", "Future installation savings",
        "Future disposal savings", "Repair savings", "Loss-of-use savings",
        "Pre-grant NPV", "One-time grant", "After-grant NPV",
    ]
    upfront = row["signed_upfront_difference_usd"]
    # Separate current capex/disposal from their full-horizon component NPVs.
    current_installation = row["current_installation_benefit_usd"]
    current_disposal = row["current_disposal_benefit_usd"]
    values = [
        -upfront, row["npv_installation_usd"] - current_installation,
        row["npv_disposal_usd"] - current_disposal,
        row["npv_repair_usd"], row["npv_loss_of_use_usd"],
        0, row["economic_grant_usd"], 0,
    ]
    figure = go.Figure(go.Waterfall(
        x=labels, y=values,
        measure=["relative"] * 5 + ["total", "relative", "total"],
        connector={"line": {"color": "#696f7b"}},
        hovertemplate="%{x}<br>%{y:$,.2f}<extra></extra>",
    ))
    figure.update_layout(
        title="Economic gap reconciliation at the installation year",
        yaxis_title="Discounted benefit / cost (real 2026 USD)",
        margin={"l": 24, "r": 24, "t": 60, "b": 40},
    )
    return figure
