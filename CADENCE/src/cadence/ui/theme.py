"""Shared presentation constants for the CADENCE Streamlit application."""

from html import escape

THEME = {
    "primary": "#1e3a8a",
    "primary_light": "#bfdbfe",
    "surface": "#fefefe",
    "surface_alt": "#f8fafc",
    "text": "#1f2937",
    "muted": "#6b7280",
    "border": "#d1d5db",
}

MATERIAL_COLORS = {
    "Asphalt": ("#9e9e9e", "#616161", "#212121"),
    "Metal": ("#e0e0e0", "#90a4ae", "#455a64"),
    "Tile": ("#ffe0b2", "#bcaaa4", "#5d4037"),
}

SCENARIO_COLORS = {
    "BASELINE_CURRENT": THEME["primary"],
    "NEW_ASPHALT": "#424242",
    "NEW_METAL": "#607d8b",
    "NEW_TILE": "#8d6e63",
}

APP_CSS = f"""
<style>
    .block-container {{ max-width: 1500px; padding-top: 1.25rem; }}
    div[data-testid="stMetric"] {{
        background: {THEME['surface_alt']};
        border: 1px solid {THEME['border']};
        border-radius: 0.375rem;
        padding: 0.85rem 0.95rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    div[data-testid="stMetric"] label {{ color: #475569; font-weight: 600; }}
    div[data-testid="stDataFrame"] {{
        border: 1px solid {THEME['border']};
        border-radius: 0.375rem;
        overflow: hidden;
    }}
    section[data-testid="stSidebar"] {{ background: {THEME['surface_alt']}; }}
    .cadence-header {{
        padding: 1.25rem 1.5rem;
        background: {THEME['primary']};
        border-radius: 0.375rem;
        margin-bottom: 1.5rem;
    }}
    .cadence-header h1 {{
        color: #fff; margin: 0; font-size: 1.6rem; font-weight: 700;
        letter-spacing: 0;
    }}
    .cadence-header p {{
        color: {THEME['primary_light']}; margin: 0.25rem 0 0; font-size: 0.875rem;
    }}
    .cadence-section {{
        background: {THEME['primary']}; color: #fff; padding: 0.75rem 0.9rem;
        border-radius: 0.375rem; font-weight: 700; margin-bottom: 0.75rem;
    }}
</style>
"""


def page_header(title: str, subtitle: str) -> str:
    """Return the shared application header markup."""
    return (
        '<div class="cadence-header">'
        f"<h1>{escape(title)}</h1><p>{escape(subtitle)}</p>"
        "</div>"
    )


def section_header(title: str) -> str:
    """Return compact section-header markup."""
    return f'<div class="cadence-section">{escape(title)}</div>'