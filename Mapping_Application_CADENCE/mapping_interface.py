import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

# 1. Configuration & Constants
CURRENT_YEAR = 2026
THEME = {
    "primary": "#1e3a8a",
    "primary_light": "#bfdbfe",
    "surface": "#fefefe",
    "surface_alt": "#f8fafc",
    "text": "#1f2937",
    "muted": "#6b7280",
    "border": "#d1d5db",
}
EUL_DEFAULTS = {
    "Asphalt": 10,
    "Metal": 40,
    "Ceramic": 30
}
TYPE_ALIASES = {
    "Asphalt": "Asphalt",
    "Metal": "Metal",
    "Steel": "Metal",
    "Ceramic": "Ceramic",
}

# Base colors for calculations (Light to Dark hex mappings)
COLOR_RAMPS = {
    "Asphalt": ["#9E9E9E", "#616161", "#212121"], # Light grey to Pitch Black
    "Metal": ["#E0E0E0", "#90A4AE", "#455A64"],   # Light silver to Dark steel slate
    "Ceramic": ["#FFE0B2", "#BCAAA4", "#5D4037"]  # Light cream to Dark tan/brown
}
RANKING_COLORS = {
    "Below Baseline": "#dc2626",
    "Baseline (Code)": "#d97706",
    "Upgrade": "#2563eb",
    "Super Upgrade": "#16a34a",
}

st.set_page_config(layout="wide", page_title="CIRCAD Mapping Interface")
st.markdown(
    """
    <style>
        .block-container {
            max-width: 1500px;
            padding-top: 1.25rem;
        }
        div[data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #d1d5db;
            border-radius: 0.375rem;
            padding: 0.85rem 0.95rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        div[data-testid="stMetric"] label {
            color: #475569;
            font-weight: 600;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid #d1d5db;
            border-radius: 0.375rem;
            overflow: hidden;
        }
        section[data-testid="stSidebar"] {
            background: #f8fafc;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Page header — financial theme styling via markdown
st.markdown(
    """
    <div style="
        padding: 1.25rem 1.5rem;
        background-color: #1e3a8a;
        border-radius: 0.375rem;
        margin-bottom: 1.5rem;
    ">
        <h1 style="color: #ffffff; margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: 0.01em;">
            CIRCAD Interactive Asset Mapping Interface
        </h1>
        <p style="color: #bfdbfe; margin: 0.25rem 0 0 0; font-size: 0.875rem; font-weight: 400;">
            Roofing Asset Registry · Remaining Useful Life · Locality Ranking
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# 2. Helper Functions for Business Logic
def normalize_roof_type(raw_type):
    roof_type = str(raw_type).strip().title()
    return TYPE_ALIASES.get(roof_type, roof_type)

def calculate_metrics(row):
    type = normalize_roof_type(row['Type'])
    age = pd.to_numeric(row['Age'], errors='coerce')
    if pd.isna(age):
        age = 0
    
    # Fallback if type is unknown
    eul = EUL_DEFAULTS.get(type, 20) 
    rul = max(0, eul - age)
    replacement_year = CURRENT_YEAR + rul
    
    # Locality Ranking Logic
    # RUL is not used in ranking of assets — a calculation database for each county
    # will determine the ideal roofing type based on cost/benefit analysis (separate repo).
    if rul <= 2:
        ranking = "Below Baseline"
    elif rul <= 5:
        ranking = "Baseline (Code)"
    elif rul <= 12:
        ranking = "Upgrade"
    else:
        ranking = "Super Upgrade"
        
    return pd.Series([type, age, rul, replacement_year, ranking])

def get_color_shade(type, age):
    type = normalize_roof_type(type)
    eul = EUL_DEFAULTS.get(type, 20)
    ramp = COLOR_RAMPS.get(type, ["#E0E0E0", "#9E9E9E", "#212121"])
    
    # Determine life-stage ratio for shading
    ratio = age / eul
    if ratio < 0.33:
        return ramp[0] # Lighter
    elif ratio < 0.66:
        return ramp[1] # Medium
    else:
        return ramp[2] # Darker (Older)

def get_roof_marker_html(type, age):
    marker_color = get_color_shade(type, age)
    return f"""
    <div style="position: relative; width: 34px; height: 28px; filter: drop-shadow(0 2px 2px rgba(15,23,42,0.35));">
        <div style="
            position: absolute;
            left: 3px;
            top: 2px;
            width: 0;
            height: 0;
            border-left: 14px solid transparent;
            border-right: 14px solid transparent;
            border-bottom: 16px solid {marker_color};
        "></div>
        <div style="
            position: absolute;
            left: 5px;
            top: 16px;
            width: 24px;
            height: 7px;
            background: {marker_color};
            border: 1px solid #111827;
            border-top: 0;
            border-radius: 0 0 3px 3px;
        "></div>
    </div>
    """

def render_range_filter(label, series):
    min_value = int(series.min())
    max_value = int(series.max())
    if min_value == max_value:
        st.caption(f"{label}: {min_value}")
        return min_value, max_value
    return st.slider(label, min_value, max_value, (min_value, max_value))

def type_cell_style(value):
    material_colors = {
        "Asphalt": "#212121",
        "Metal": "#455A64",
        "Ceramic": "#5D4037",
    }
    color = material_colors.get(value, THEME["muted"])
    return f"color: {color}; font-weight: 700; background-color: #f8fafc;"

def ranking_cell_style(value):
    color = RANKING_COLORS.get(value, THEME["muted"])
    return f"color: {color}; font-weight: 700; background-color: #f8fafc;"

def style_registry_table(dataframe):
    return (
        dataframe.style
        .format({
            "Age": "{:.0f}",
            "RUL": "{:.0f}",
            "Replacement Year": "{:.0f}",
            "Latitude": "{:.5f}",
            "Longitude": "{:.5f}",
        })
        .map(type_cell_style, subset=["Type"])
        .map(ranking_cell_style, subset=["Ranking"])
        .set_properties(**{
            "border-color": THEME["border"],
            "color": THEME["text"],
        })
        .set_table_styles([
            {
                "selector": "th",
                "props": [
                    ("background-color", THEME["primary"]),
                    ("color", "#ffffff"),
                    ("font-weight", "600"),
                    ("border-color", THEME["primary"]),
                ],
            },
            {
                "selector": "td",
                "props": [("border-color", THEME["border"])],
            },
        ])
    )

def render_summary_card(label, value):
    st.markdown(
        f"""
        <div style="
            background: #f8fafc;
            border: 1px solid #d1d5db;
            border-radius: 0.375rem;
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.85rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        ">
            <div style="color:#475569; font-size:0.8rem; font-weight:700; line-height:1.25; margin-bottom:0.35rem;">
                {label}
            </div>
            <div style="color:#111827; font-size:1.7rem; font-weight:500; line-height:1.1;">
                {value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# 3. Sidebar Tool: Address to Lat/Long Converter
# Removed from this interface — geocoding is an activity performed before the input
# Excel file is uploaded. Users can use an external geocoding tool to find coordinates.

# 4. Main App: File Upload & Map Engine
st.markdown("#### Upload Asset Registry")
uploaded_file = st.file_uploader(
    "Upload an Excel file containing your asset data",
    type=["xlsx", "xls"],
    help="Required columns: Latitude, Longitude, Type, Age"
)

if not uploaded_file:
    import os
    for local_path in ["data/raw/sample_assets.xlsx", "sample_assets.xlsx"]:
        if os.path.exists(local_path):
            uploaded_file = local_path
            st.info(f"Automatically loading default asset file from `{local_path}`")
            break

if uploaded_file:
    # Read Data
    df = pd.read_excel(uploaded_file)
    
    # Validate expected columns
    required_cols = {'Latitude', 'Longitude', 'Type', 'Age'}
    if not required_cols.issubset(df.columns):
        st.error(f"Excel file must contain these exact columns: {required_cols}")
    else:
        # Process Data
        df[['Type', 'Age', 'RUL', 'Replacement Year', 'Ranking']] = df.apply(calculate_metrics, axis=1)

        filter_col, map_col, summary_col = st.columns([1.15, 3.35, 1.2], gap="large")

        with filter_col:
            st.markdown(
                """
                <div style="background:#1e3a8a; color:#ffffff; padding:0.75rem 0.9rem;
                            border-radius:0.375rem; font-weight:700; margin-bottom:0.75rem;">
                    Filter Assets
                </div>
                """,
                unsafe_allow_html=True,
            )
            type_options = sorted(df['Type'].dropna().unique())
            ranking_options = [ranking for ranking in RANKING_COLORS if ranking in df['Ranking'].unique()]

            selected_types = st.multiselect("Roofing Type", type_options, default=type_options)
            age_range = render_range_filter("Age", df['Age'])
            rul_range = render_range_filter("RUL", df['RUL'])
            replacement_year_range = render_range_filter("Replacement Year", df['Replacement Year'])
            selected_rankings = st.multiselect("Ranking", ranking_options, default=ranking_options)

        filtered_df = df[
            df['Type'].isin(selected_types)
            & df['Age'].between(age_range[0], age_range[1])
            & df['RUL'].between(rul_range[0], rul_range[1])
            & df['Replacement Year'].between(replacement_year_range[0], replacement_year_range[1])
            & df['Ranking'].isin(selected_rankings)
        ].copy()

        with filter_col:
            st.caption(f"Showing {len(filtered_df)} of {len(df)} assets")

        with summary_col:
            st.markdown(
                """
                <div style="background:#1e3a8a; color:#ffffff; padding:0.75rem 0.9rem;
                            border-radius:0.375rem; font-weight:700; margin-bottom:0.75rem;">
                    Portfolio Summary
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("Based on active filters")
            render_summary_card("Total Assets", len(filtered_df))
            render_summary_card(
                "Avg. Remaining Useful Life",
                f"{filtered_df['RUL'].mean():.1f} yrs" if not filtered_df.empty else "--"
            )
            render_summary_card(
                "Avg. Asset Age",
                f"{filtered_df['Age'].mean():.1f} yrs" if not filtered_df.empty else "--"
            )
            render_summary_card(
                "Assets Needing Replacement <= 2 yrs",
                int((filtered_df['RUL'] <= 2).sum()) if not filtered_df.empty else 0
            )

        with map_col:
            st.markdown("#### Asset Map")
            if filtered_df.empty:
                st.warning("No assets match the active filters.")
            else:
                # Initialize Base Map centered around the filtered data average
                start_lat = filtered_df['Latitude'].mean()
                start_long = filtered_df['Longitude'].mean()
                m = folium.Map(
                    location=[start_lat, start_long],
                    zoom_start=13,
                    tiles="CartoDB positron",
                    control_scale=True,
                )
                
                # Add roof markers to Map
                for idx, row in filtered_df.iterrows():
                    badge_color = RANKING_COLORS.get(row['Ranking'], THEME["muted"])

                    # Hover HTML Tooltip — styled to match the financial theme
                    tooltip_html = f"""
                    <div style="font-family: Inter, sans-serif; font-size: 12px; line-height: 1.6;
                                color: #1f2937; min-width: 200px;">
                        <div style="background:#1e3a8a; color:#fff; padding:6px 10px;
                                    border-radius:4px 4px 0 0; font-weight:600; font-size:13px;">
                            Asset Details
                        </div>
                        <div style="padding: 8px 10px; border: 1px solid #d1d5db;
                                    border-top: none; border-radius: 0 0 4px 4px; background:#fefefe;">
                            <b>Type:</b> {row['Type']}<br>
                            <b>Age:</b> {int(row['Age'])} years<br>
                            <b>RUL:</b> {int(row['RUL'])} years remaining<br>
                            <b>Projected Replacement:</b> {int(row['Replacement Year'])}<br>
                            <hr style="margin: 6px 0; border-color: #d1d5db;">
                            <b>Locality Ranking:</b>&nbsp;
                            <span style="color:{badge_color}; font-weight:600;">{row['Ranking']}</span>
                        </div>
                    </div>
                    """
                    
                    folium.Marker(
                        location=[row['Latitude'], row['Longitude']],
                        popup=folium.Popup(tooltip_html, max_width=300),
                        tooltip=folium.Tooltip(tooltip_html),
                        icon=folium.DivIcon(
                            html=get_roof_marker_html(row['Type'], row['Age']),
                            icon_size=(34, 28),
                            icon_anchor=(17, 26),
                            popup_anchor=(0, -26),
                        ),
                    ).add_to(m)
                
                # Legend — styled to match the financial theme
                legend_html = '''
                <div style="
                    position: fixed; bottom: 50px; left: 50px;
                    width: 250px;
                    background-color: #fefefe;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    z-index: 9999;
                    font-family: Inter, sans-serif;
                    font-size: 12px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
                    overflow: hidden;
                ">
                    <div style="background:#1e3a8a; color:#fff; padding:8px 12px; font-weight:600; font-size:13px;">
                        Roofing Type &amp; Age Legend
                    </div>
                    <div style="padding: 10px 12px; color: #1f2937; line-height: 1.9;">
                        <span style="display:inline-block; width:0; height:0; border-left:6px solid transparent; border-right:6px solid transparent; border-bottom:9px solid #212121;"></span>&nbsp;<b>Asphalt</b> &nbsp;<span style="color:#888; font-size:11px;">grey to black</span><br>
                        <span style="display:inline-block; width:0; height:0; border-left:6px solid transparent; border-right:6px solid transparent; border-bottom:9px solid #455A64;"></span>&nbsp;<b>Metal</b> &nbsp;<span style="color:#888; font-size:11px;">silver to slate</span><br>
                        <span style="display:inline-block; width:0; height:0; border-left:6px solid transparent; border-right:6px solid transparent; border-bottom:9px solid #5D4037;"></span>&nbsp;<b>Ceramic</b> &nbsp;<span style="color:#888; font-size:11px;">cream to brown</span><br>
                        <hr style="border-color:#d1d5db; margin: 6px 0;">
                        <span style="color:#6b7280; font-size:11px;">Lighter shade = newer &nbsp;|&nbsp; Darker = older</span>
                    </div>
                </div>
                '''
                m.get_root().html.add_child(folium.Element(legend_html))
                
                map_left, map_center, map_right = st.columns([0.04, 0.92, 0.04])
                with map_center:
                    st_folium(m, width=820, height=620)
            
            st.markdown("#### Processed Asset Registry")
            if filtered_df.empty:
                st.info("Adjust the filters to display registry records.")
            else:
                registry_df = filtered_df.sort_values(["Replacement Year", "RUL", "Type"])
                st.dataframe(style_registry_table(registry_df), width="stretch", hide_index=True)