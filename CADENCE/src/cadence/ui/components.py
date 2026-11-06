"""Reusable visual components for the CADENCE Streamlit application."""

from __future__ import annotations

from html import escape
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from cadence.ui.theme import MATERIAL_COLORS, THEME


def render_summary_card(label: str, value: str) -> None:
    """Render one compact portfolio metric card."""
    st.markdown(
        f"""
        <div style="background:{THEME['surface_alt']};border:1px solid {THEME['border']};
                    border-radius:0.375rem;padding:0.85rem 0.95rem;margin-bottom:0.7rem;
                    box-shadow:0 1px 2px rgba(15,23,42,0.04);">
            <div style="color:#475569;font-size:0.8rem;font-weight:700;
                        line-height:1.25;margin-bottom:0.35rem;">{escape(label)}</div>
            <div style="color:#111827;font-size:1.55rem;font-weight:500;line-height:1.1;">
                {escape(value)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_asset_map(frame: pd.DataFrame, key: str) -> None:
    """Render filtered source assets as recognizable roof markers."""
    if frame.empty:
        st.warning("No assets match the active filters.")
        return
    ages = pd.to_numeric(frame["roof_age"], errors="coerce")
    minimum_age = float(ages.min())
    maximum_age = float(ages.max())
    asset_map = folium.Map(
        location=[frame["latitude"].mean(), frame["longitude"].mean()],
        zoom_start=6,
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
        control_scale=True,
    )
    for row in frame.to_dict(orient="records"):
        material = str(row["official_material"])
        age = float(row["roof_age"])
        color = _age_color(material, age, minimum_age, maximum_age)
        tooltip = _asset_tooltip(row)
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(tooltip, max_width=320),
            tooltip=folium.Tooltip(tooltip),
            icon=folium.DivIcon(
                html=_roof_marker(color),
                icon_size=(34, 28),
                icon_anchor=(17, 26),
                popup_anchor=(0, -26),
            ),
        ).add_to(asset_map)
    asset_map.get_root().html.add_child(folium.Element(_map_legend()))
    st_folium(asset_map, height=560, use_container_width=True, key=key)


def _age_color(material: str, age: float, minimum: float, maximum: float) -> str:
    ramp = MATERIAL_COLORS.get(material, ("#d1d5db", "#6b7280", "#1f2937"))
    if maximum <= minimum:
        return ramp[1]
    position = (age - minimum) / (maximum - minimum)
    return ramp[0] if position < 1 / 3 else ramp[1] if position < 2 / 3 else ramp[2]


def _roof_marker(color: str) -> str:
    return f"""
    <div style="position:relative;width:34px;height:28px;filter:drop-shadow(0 2px 2px rgba(15,23,42,.35));">
      <div style="position:absolute;left:3px;top:2px;width:0;height:0;
                  border-left:14px solid transparent;border-right:14px solid transparent;
                  border-bottom:16px solid {color};"></div>
      <div style="position:absolute;left:5px;top:16px;width:24px;height:7px;
                  background:{color};border:1px solid #111827;border-top:0;
                  border-radius:0 0 3px 3px;"></div>
    </div>
    """


def _asset_tooltip(row: dict[str, Any]) -> str:
    details = [
        ("Asset ID", row.get("asset_id")),
        ("Current roof", row.get("official_material")),
        ("Roof age", _unit(row.get("roof_age"), "years")),
        ("Roof area", _unit(row.get("roof_area_sqft"), "sq ft", comma=True)),
        ("Terrain", row.get("Terrain", row.get("terrain_label"))),
    ]
    if _present(row.get("insured_value")):
        details.append(("Insured value", f"${float(row['insured_value']):,.0f}"))
    if _present(row.get("install_year")):
        details.append(("Installation year", f"{int(row['install_year'])}"))
    lines = "".join(
        f"<b>{escape(label)}:</b> {escape(str(value))}<br>"
        for label, value in details
        if _present(value)
    )
    return f"""
    <div style="font-family:sans-serif;font-size:12px;line-height:1.6;color:{THEME['text']};min-width:210px;">
      <div style="background:{THEME['primary']};color:#fff;padding:6px 10px;
                  border-radius:4px 4px 0 0;font-weight:600;font-size:13px;">Asset Details</div>
      <div style="padding:8px 10px;border:1px solid {THEME['border']};border-top:0;
                  border-radius:0 0 4px 4px;background:{THEME['surface']};">{lines}</div>
    </div>
    """


def _unit(value: Any, unit: str, comma: bool = False) -> str | None:
    if not _present(value):
        return None
    number = float(value)
    formatted = f"{number:,.0f}" if comma else f"{number:g}"
    return f"{formatted} {unit}"


def _present(value: Any) -> bool:
    return value is not None and not pd.isna(value) and str(value).strip() != ""


def _map_legend() -> str:
    return f"""
    <div style="position:fixed;bottom:45px;left:45px;width:235px;background:{THEME['surface']};
                border:1px solid {THEME['border']};border-radius:6px;z-index:9999;
                font-family:sans-serif;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);">
      <div style="background:{THEME['primary']};color:#fff;padding:8px 12px;font-weight:600;">
        Roofing Material and Age
      </div>
      <div style="padding:9px 12px;color:{THEME['text']};line-height:1.9;">
        <b style="color:#212121">Asphalt</b> · gray to black<br>
        <b style="color:#455a64">Metal</b> · silver to slate<br>
        <b style="color:#5d4037">Tile</b> · cream to brown<br>
        <span style="color:{THEME['muted']};font-size:11px;">Lighter = newer · darker = older</span>
      </div>
    </div>
    """