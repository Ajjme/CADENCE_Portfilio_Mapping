"""Geography and interactive maps for saved Alternative Analysis results."""

from __future__ import annotations

from html import escape
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import streamlit as st
from branca.colormap import LinearColormap
from streamlit_folium import st_folium

from cadence.reference_data.economics_assets import FIPS_TO_STATE
from cadence.reference_data.material_price_expansion import normalize_county_geoid
from cadence.ui.paths import CLIMATE_ZONES, DATA_ROOT
from cadence.ui.results_data import MAP_REGIONS

ZCTA_PATH = DATA_ROOT / "Geography/Census_TIGER/raw/v2020/tl_2020_us_zcta520.zip"
BASE_TILES = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
)


@st.cache_data(show_spinner=False)
def load_map_boundaries(region: str, identifiers: tuple[str, ...], bounds: tuple[float, ...]) -> gpd.GeoDataFrame:
    """Return only the selected 2020 ZCTAs or counties/states in WGS84."""
    if region not in MAP_REGIONS:
        raise ValueError("unsupported region")
    if region == "ZIP / ZCTA":
        source = f"zip://{ZCTA_PATH.resolve()}"
        shapes = gpd.read_file(source, bbox=bounds)[["ZCTA5CE20", "geometry"]]
        shapes["region_id"] = shapes["ZCTA5CE20"].astype(str).str.zfill(5)
    else:
        shapes = gpd.read_file(CLIMATE_ZONES)[["GEOID", "geometry"]]
        shapes["county_fips"] = shapes["GEOID"].map(normalize_county_geoid)
        if region == "County":
            shapes["region_id"] = shapes["county_fips"]
        else:
            shapes["region_id"] = shapes["county_fips"].str[:2].map(FIPS_TO_STATE)
            shapes = shapes.loc[shapes["region_id"].isin(identifiers)]
            shapes = shapes.dissolve(by="region_id", as_index=False)
    shapes = shapes.loc[shapes["region_id"].isin(identifiers), ["region_id", "geometry"]]
    if shapes["region_id"].duplicated().any():
        raise ValueError("regional boundary identifiers are duplicated")
    if shapes.crs is None:
        raise ValueError("regional boundaries have no coordinate system")
    shapes = shapes.to_crs("EPSG:4326")
    shapes["geometry"] = shapes.geometry.simplify(0.002 if region == "ZIP / ZCTA" else 0.005, preserve_topology=True)
    return shapes


def render_results_map(
    rows: pd.DataFrame,
    metric: str,
    label: str,
    key: str,
    domain: float,
    regions: pd.DataFrame | None = None,
    boundaries: gpd.GeoDataFrame | None = None,
    region_name: str = "",
) -> None:
    """Draw results with a zero-centered scale and a distinct missing state."""
    if rows.empty:
        st.info("No assets are available for this map.")
        return
    domain = max(float(domain), 1.0)
    palette = LinearColormap(["#b12a34", "#f1f2ef", "#007c7a"], vmin=-domain, vmax=domain)
    palette.caption = f"{label} · real 2026 USD · red negative / teal positive"
    asset_map = folium.Map(
        location=[float(rows["latitude"].mean()), float(rows["longitude"].mean())],
        zoom_start=5, tiles=BASE_TILES, attr="Tiles &copy; Esri", control_scale=True,
    )
    if regions is None:
        for row in rows.to_dict("records"):
            value = row[metric]
            color = "#80858c" if pd.isna(value) else palette(float(value))
            details = (
                f"<b>{escape(str(row['asset_id']))}</b><br>"
                f"Replacement: {escape(str(row['scenario_id']).replace('NEW_', '').title())}<br>"
                f"Avoided damage: {_money(row['cumulative_avoided_damage_usd'])}<br>"
                f"NPV: {_money(row['net_present_value_usd'])}"
            )
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]], radius=8,
                color="#ffffff", weight=1.5, fill=True, fill_color=color,
                fill_opacity=0.95, tooltip=folium.Tooltip(details),
                popup=folium.Popup(details, max_width=320),
            ).add_to(asset_map)
        if len(rows) > 1:
            asset_map.fit_bounds([[rows["latitude"].min(), rows["longitude"].min()],
                                  [rows["latitude"].max(), rows["longitude"].max()]],
                                 padding=(32, 32), max_zoom=11)
    else:
        if boundaries is None:
            raise ValueError("regional map requires boundaries")
        field = MAP_REGIONS[region_name]
        shapes = boundaries.merge(regions, left_on="region_id", right_on=field, validate="1:1")
        for item in shapes.itertuples():
            value = item.value
            color = "#80858c" if pd.isna(value) else palette(float(value))
            details = (
                f"<b>{escape(region_name)} {escape(str(item.region_id))}</b><br>"
                f"{escape(label)}: {_money(value)}<br>"
                f"Assets: {item.asset_count:,}<br>Missing: {item.missing_count:,}<br>"
                f"Replacements: {escape(item.replacement_mix)}"
            )
            folium.GeoJson(
                item.geometry.__geo_interface__,
                style_function=lambda _feature, fill=color: {
                    "fillColor": fill, "color": "#39434b", "weight": 1,
                    "fillOpacity": 0.74,
                },
                tooltip=folium.Tooltip(details), popup=folium.Popup(details, max_width=320),
            ).add_to(asset_map)
        if not shapes.empty:
            west, south, east, north = shapes.total_bounds
            asset_map.fit_bounds([[south, west], [north, east]], padding=(24, 24), max_zoom=11)
    palette.add_to(asset_map)
    asset_map.get_root().html.add_child(folium.Element(
        '<div style="position:fixed;bottom:32px;left:32px;z-index:9999;'
        'background:#fff;padding:5px 9px;border:1px solid #ccc;font-size:12px">'
        'Gray = unavailable</div>'
    ))
    st_folium(asset_map, height=520, use_container_width=True, key=key, returned_objects=[])


def _money(value: object) -> str:
    return "Unavailable" if pd.isna(value) or not np.isfinite(float(value)) else f"${float(value):,.0f}"