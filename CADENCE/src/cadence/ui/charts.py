"""Plotly figures for current Alternative Analysis outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative

from cadence.ui.theme import SCENARIO_COLORS, THEME
from cadence.vulnerability.expected_damage import RETURN_PERIODS

SCENARIO_ORDER = ("BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
MATERIAL_NAMES = {
    "OFFICIAL_ASPHALT": "Asphalt",
    "OFFICIAL_METAL": "Metal",
    "OFFICIAL_TILE": "Tile",
}


def market_share_figure(stock: pd.DataFrame) -> go.Figure:
    """Show post-decision roof stock as a share of the original portfolio."""
    figure = go.Figure()
    years = sorted(stock["year"].unique())
    colors = {"OFFICIAL_ASPHALT": "#696f7b", "OFFICIAL_METAL": "#19817d",
              "OFFICIAL_TILE": "#c08b3a", "UNKNOWN": "#b9bdc1"}
    for material, color in colors.items():
        records = stock.loc[stock["material_id"] == material].set_index("year").reindex(years)
        figure.add_bar(name=MATERIAL_NAMES.get(material, "Unknown"), x=years,
                       y=records["share_percent"].fillna(0), customdata=records["asset_count"].fillna(0),
                       marker_color=color,
                       hovertemplate="%{x}<br>%{y:.1f}% · %{customdata:.0f} roofs<extra>%{fullData.name}</extra>")
    figure.update_layout(title="Roof stock by material", barmode="stack", yaxis_title="Share of portfolio (%)",
                         xaxis_title="Year", yaxis_range=[0, 100], legend_title_text="Roof material",
                         margin=dict(l=24, r=24, t=56, b=30))
    return figure


def market_cost_figure(costs: pd.DataFrame) -> go.Figure:
    """Show recurring and replacement costs paid in each modeled year."""
    figure = go.Figure()
    colors = {"repair_usd": "#cf7770", "loss_of_use_usd": "#e0ae68",
              "material_usd": "#19817d", "labor_usd": "#5aa6a0",
              "disposal_usd": "#7980a2", "carbon_usd": "#a69f77"}
    for column, color in colors.items():
        figure.add_bar(name=COST_COMPONENTS[column], x=costs["year"], y=costs[column],
                       customdata=costs[["replacement_count", "eul_replacements", "damage_replacements", "unknown_count"]],
                       marker_color=color,
                       hovertemplate="%{x}<br>%{y:$,.0f}<br>Replacements: %{customdata[0]:.0f}"
                                     " (EUL %{customdata[1]:.0f}, damage %{customdata[2]:.0f})"
                                     "<br>Unknown: %{customdata[3]:.0f}<extra>%{fullData.name}</extra>")
    figure.update_layout(title="Expected annual portfolio costs", barmode="stack", xaxis_title="Year",
                         yaxis_title="Real 2026 USD", margin=dict(l=24, r=24, t=56, b=30))
    return figure
COST_COMPONENTS = {
    "material_usd": "Material",
    "labor_usd": "Labor",
    "repair_usd": "Expected repair",
    "loss_of_use_usd": "Loss of use",
    "disposal_usd": "Disposal",
    "carbon_usd": "Carbon",
}


def scenario_labels(current_material_id: str | None, portfolio: bool = False) -> dict[str, str]:
    """Return stable report labels for all four scenarios."""
    installed = MATERIAL_NAMES.get(str(current_material_id), "roof")
    return {
        "BASELINE_CURRENT": "Installed roofs" if portfolio else f"Installed roof {installed}",
        "NEW_ASPHALT": "New asphalt",
        "NEW_METAL": "New metal",
        "NEW_TILE": "New tile",
    }


def time_series_figure(
    frame: pd.DataFrame,
    title: str,
    labels: dict[str, str],
    portfolio: bool = False,
) -> go.Figure:
    """Build grouped yearly bars with installation/replacement diamonds."""
    figure = go.Figure()
    for scenario in SCENARIO_ORDER:
        rows = frame.loc[frame["scenario_id"] == scenario].sort_values("year")
        figure.add_bar(
            name=labels[scenario],
            x=rows["year"],
            y=rows["metric_value"],
            marker_color=SCENARIO_COLORS[scenario],
            hovertemplate="%{x}<br>%{y:$,.0f}<extra>%{fullData.name}</extra>",
        )
        if portfolio:
            events = rows.loc[
                (rows["installation_event_count"] > 0)
                | (rows["replacement_event_count"] > 0)
            ]
            event_text = [
                f"Installations: {int(row.installation_event_count)}<br>"
                f"Burnout replacements: {int(row.replacement_event_count)}"
                for row in events.itertuples()
            ]
        else:
            events = rows.loc[rows["installation_event"].fillna(False)]
            event_text = [
                "Initial installation" if row.initial_installation_event
                else "Burnout replacement" if row.burnout_replacement_event
                else "Installation"
                for row in events.itertuples()
            ]
        figure.add_scatter(
            name=f"{labels[scenario]} events",
            x=events["year"],
            y=events["metric_value"],
            mode="markers",
            marker={
                "symbol": "diamond",
                "size": 10,
                "color": SCENARIO_COLORS[scenario],
                "line": {"color": "#ffffff", "width": 1},
            },
            text=event_text,
            hovertemplate="%{x}<br>%{text}<br>%{y:$,.0f}<extra>%{fullData.name}</extra>",
            showlegend=False,
        )
    return _style_figure(figure, title, "Year", "Real 2026 USD", "group")


def comparison_figure(frame: pd.DataFrame, title: str) -> go.Figure:
    """Build an alternative NPV comparison bar chart."""
    labels = scenario_labels(None)
    figure = go.Figure()
    for scenario in ("NEW_ASPHALT", "NEW_METAL", "NEW_TILE"):
        rows = frame.loc[frame["scenario_id"] == scenario]
        value = rows["net_present_value_usd"].iloc[0] if len(rows) else None
        figure.add_bar(
            name=labels[scenario],
            x=[labels[scenario]],
            y=[value],
            marker_color=SCENARIO_COLORS[scenario],
            hovertemplate="%{x}<br>%{y:$,.0f}<extra></extra>",
        )
    return _style_figure(figure, title, "", "Real 2026 USD", "group")


def cost_allocation_figure(frame: pd.DataFrame, title: str, labels: dict[str, str]) -> go.Figure:
    """Compare four scenarios with a consistent color for each cost stream."""
    figure = go.Figure()
    colors = ("#65bfa2", "#efb867", "#dd7975", "#83a7de", "#b7a0d7", "#d1c078")
    ordered = frame.set_index("scenario_id").reindex(SCENARIO_ORDER)
    x_values = [labels[scenario] for scenario in SCENARIO_ORDER]
    for (column, name), color in zip(COST_COMPONENTS.items(), colors):
        figure.add_bar(
            name=name, x=x_values, y=ordered[column], marker_color=color,
            hovertemplate=f"%{{x}}<br>{name}: %{{y:$,.0f}}<extra></extra>",
        )
    totals = ordered["total_usd"]
    figure.add_scatter(
        x=x_values, y=ordered[list(COST_COMPONENTS)].fillna(0).sum(axis=1),
        mode="text", text=["Incomplete" if pd.isna(value) else f"${value:,.0f}" for value in totals],
        textposition="top center", showlegend=False, hoverinfo="skip",
    )
    _style_figure(figure, title, "", "Real 2026 USD", "stack")
    figure.update_layout(margin={"l": 60, "r": 25, "t": 90, "b": 70},
                         uniformtext={"minsize": 10, "mode": "hide"})
    return figure


def wind_return_period_figure(frame: pd.DataFrame, title: str) -> go.Figure:
    """Plot observed gusts and interpolate wind speed against log return years."""
    figure = go.Figure()
    periods = np.asarray(RETURN_PERIODS, dtype=float)
    for index, row in enumerate(frame.itertuples(index=False)):
        gusts = np.array([getattr(row, f"rp_{period}") for period in RETURN_PERIODS])
        sampled_periods = np.concatenate([
            *(np.geomspace(start, end, 17)[:-1] for start, end in zip(periods[:-1], periods[1:])),
            periods[-1:],
        ])
        sampled_gusts = np.interp(np.log(sampled_periods), np.log(periods), gusts)
        color = qualitative.Plotly[index % len(qualitative.Plotly)]
        hover = (
            f"Asset: {row.asset_id}<br>Grid ID: {row.wind_grid_id}"
            "<br>Return period: %{x:.1f} years<br>3-second gust: %{y:.1f} mph"
            "<extra></extra>"
        )
        figure.add_scatter(
            name=str(row.asset_id), x=sampled_periods, y=sampled_gusts,
            mode="lines", line={"color": color, "width": 2},
            hovertemplate=hover,
        )
        figure.add_scatter(
            x=periods, y=gusts, mode="markers", showlegend=False,
            marker={"color": color, "size": 8, "line": {"color": THEME["surface"], "width": 1}},
            hovertemplate=hover,
        )
    _style_figure(figure, title, "Return period (years)", "3-second gust (mph)", "group")
    figure.update_xaxes(type="log", tickvals=list(RETURN_PERIODS), range=[np.log10(9), np.log10(550)])
    return figure


def _style_figure(
    figure: go.Figure,
    title: str,
    x_title: str,
    y_title: str,
    bar_mode: str,
) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 17}},
        barmode=bar_mode,
        paper_bgcolor=THEME["surface"],
        plot_bgcolor=THEME["surface_alt"],
        font={"color": THEME["text"]},
        xaxis={"title": x_title, "gridcolor": THEME["border"], "fixedrange": True},
        yaxis={"title": y_title, "gridcolor": THEME["border"], "zerolinecolor": THEME["border"]},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        margin={"l": 60, "r": 25, "t": 85, "b": 55},
        height=470,
    )
    return figure