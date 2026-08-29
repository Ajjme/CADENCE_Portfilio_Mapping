"""Plotly figures for current Alternative Analysis outputs."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from cadence.ui.theme import SCENARIO_COLORS, THEME

SCENARIO_ORDER = ("BASELINE_CURRENT", "NEW_ASPHALT", "NEW_METAL", "NEW_TILE")
MATERIAL_NAMES = {
    "OFFICIAL_ASPHALT": "Asphalt",
    "OFFICIAL_METAL": "Metal",
    "OFFICIAL_TILE": "Tile",
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