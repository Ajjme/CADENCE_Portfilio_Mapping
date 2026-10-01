"""Insurance-focused Plotly figures for estimated wind roof underwriting."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from cadence.ui.charts import SCENARIO_ORDER, scenario_labels
from cadence.ui.theme import THEME


def _finish(figure: go.Figure, title: str, y_label: str) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 17}},
        paper_bgcolor=THEME["surface"], plot_bgcolor=THEME["surface_alt"],
        font={"color": THEME["text"]}, margin={"l": 55, "r": 20, "t": 75, "b": 55},
        height=360, legend={"orientation": "h", "y": 1.18, "x": 0},
        xaxis={"title": "Year", "gridcolor": THEME["border"], "dtick": 2},
        yaxis={"title": y_label, "gridcolor": THEME["border"]},
    )
    return figure


def annual_balance_figure(rows: pd.DataFrame, title: str) -> go.Figure:
    """Premium and negative payout bars with modeled margin over the same years."""
    rows = rows.sort_values("year")
    figure = go.Figure()
    figure.add_bar(
        name="Annual premium", x=rows["year"], y=rows["premium_usd"],
        marker_color="#237b66", hovertemplate="%{x}<br>Premium %{y:$,.0f}<extra></extra>",
    )
    figure.add_bar(
        name="Expected payout", x=rows["year"], y=-rows["expected_payout_usd"],
        marker_color="#d47552", hovertemplate="%{x}<br>Payout %{customdata:$,.0f}<extra></extra>",
        customdata=rows["expected_payout_usd"],
    )
    figure.add_scatter(
        name="Underwriting margin", x=rows["year"], y=rows["underwriting_margin_usd"],
        mode="lines+markers", line={"color": "#39495b", "width": 2},
        hovertemplate="%{x}<br>Margin %{y:$,.0f}<extra></extra>",
    )
    _finish(figure, title, "Real 2026 USD")
    figure.update_layout(barmode="relative")
    figure.add_hline(y=0, line_color=THEME["text"], line_width=1)
    return figure


def loss_ratio_figure(rows: pd.DataFrame) -> go.Figure:
    """Four roof alternatives by year; absent and zero-premium ratios are blank."""
    matrix = rows.pivot(index="scenario_id", columns="year", values="loss_ratio").reindex(SCENARIO_ORDER)
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    values = matrix.stack()
    maximum = max(2.0, float(values.max())) if not values.empty else 2.0
    labels = scenario_labels(None, portfolio=True)
    figure = go.Figure(go.Heatmap(
        x=list(matrix.columns), y=[labels[key] for key in matrix.index], z=matrix.to_numpy(),
        zmin=0, zmax=maximum, zmid=1,
        colorscale=[[0, "#237b66"], [0.5, "#ead28b"], [1, "#b5453e"]],
        colorbar={"title": "Payout / premium", "tickformat": ".0%"},
        hovertemplate="%{y}<br>%{x}<br>Loss ratio: %{z:.1%}<extra></extra>",
    ))
    _finish(figure, "Projected wind-roof loss ratio by option", "Roof option")
    figure.update_layout(height=300, xaxis={"title": "Year", "dtick": 2},
                         yaxis={"title": "", "autorange": "reversed"})
    return figure


def cumulative_figure(rows: pd.DataFrame, title: str) -> go.Figure:
    rows = rows.sort_values("year")
    figure = go.Figure()
    for column, name, color in (
        ("cumulative_premium_usd", "Premiums collected", "#237b66"),
        ("cumulative_payout_usd", "Expected payouts", "#d47552"),
    ):
        figure.add_scatter(
            name=name, x=rows["year"], y=rows[column], mode="lines+markers",
            line={"color": color, "width": 3},
            hovertemplate="%{x}<br>%{y:$,.0f}<extra>%{fullData.name}</extra>",
        )
    return _finish(figure, title, "Cumulative real 2026 USD")


def coverage_figure(row: pd.Series) -> go.Figure:
    """Explain deductible and insurer limit for one selected asset/year/roof."""
    repair = float(row["annual_repair_cost_usd"])
    deductible = min(repair, float(row["deductible_amount"]))
    cap = max(repair - deductible - float(row["insured_value"]), 0)
    payout = float(row["expected_payout_usd"])
    figure = go.Figure(go.Waterfall(
        orientation="h",
        y=["Expected repair", "Deductible", "Over limit", "Expected payout"],
        x=[repair, -deductible, -cap, payout],
        measure=["absolute", "relative", "relative", "total"],
        connector={"line": {"color": THEME["border"]}},
        increasing={"marker": {"color": "#d47552"}},
        decreasing={"marker": {"color": "#738b99"}},
        totals={"marker": {"color": "#237b66"}},
        hovertemplate="%{y}<br>%{x:$,.0f}<extra></extra>",
    ))
    _finish(figure, "How the policy changes modeled repair", "Real 2026 USD")
    figure.update_layout(
        margin={"l": 110, "r": 20, "t": 75, "b": 55},
        xaxis={"title": "Real 2026 USD", "tickprefix": "$"},
        yaxis={"title": "", "autorange": "reversed"}, showlegend=False,
    )
    return figure