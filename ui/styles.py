"""Global CSS theme & reading ergonomics helpers for Streamlit UI."""

from typing import Optional
import streamlit as st

_GLOBAL_CSS = """
<style>
/* Modern Judicial / Scholarly Theme */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", "PingFang SC", "Microsoft JhengHei", Roboto, sans-serif;
    color: #1e293b;
}

/* Page container breathing room */
.block-container {
    padding-top: 2rem !important;
    padding-bottom: 3.5rem !important;
    max-width: 1400px;
}

/* Metrics & Stat Cards */
div[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 14px 18px;
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.05);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
div[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
    border-color: #cbd5e1;
}
div[data-testid="stMetricLabel"] {
    font-size: 0.90rem !important;
    color: #475569 !important;
    font-weight: 600 !important;
}
div[data-testid="stMetricValue"] {
    font-size: 1.6rem !important;
    color: #1e3a8a !important;
    font-weight: 700 !important;
}

/* Modern Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 10px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    padding: 10px 20px;
    font-size: 1.0rem;
    font-weight: 600;
    color: #64748b;
    background-color: transparent;
    transition: all 0.2s ease;
}
.stTabs [aria-selected="true"] {
    color: #1d4ed8 !important;
    border-bottom: 3px solid #1d4ed8 !important;
    background-color: rgba(29, 78, 216, 0.05) !important;
}

/* Expanders */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    font-size: 0.98rem !important;
    border-radius: 8px !important;
}
div[data-testid="stExpander"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    margin-bottom: 12px;
}

/* Buttons */
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
    padding: 0.5rem 1.2rem;
    transition: all 0.15s ease-in-out;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%) !important;
    border: none !important;
    box-shadow: 0 2px 4px rgba(37, 99, 235, 0.25);
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
    transform: translateY(-1px);
}

/* Sidebar Nav Slots / Fields (一個欄位一個欄位設計，徹底杜絕 ● 圓點) */
div[data-testid="stSidebar"] div.stButton > button {
    text-align: left !important;
    justify-content: flex-start !important;
    border-radius: 9px !important;
    padding: 8px 13px !important;
    font-size: 0.94rem !important;
    font-weight: 550 !important;
    transition: all 0.16s ease-in-out !important;
    margin-bottom: 4px !important;
    width: 100% !important;
}
div[data-testid="stSidebar"] div.stButton > button:hover {
    transform: translateX(3px) !important;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
}
div[data-testid="stSidebar"] div.stButton > button[kind="primary"],
div[data-testid="stSidebar"] div.stButton > button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #2563eb 100%) !important;
    color: #ffffff !important;
    border: 1px solid #3b82f6 !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 12px rgba(30, 58, 138, 0.28) !important;
}
div[data-testid="stSidebar"] div.stButton > button[kind="secondary"],
div[data-testid="stSidebar"] div.stButton > button[data-testid="baseButton-secondary"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    color: #334155 !important;
}
div[data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover,
div[data-testid="stSidebar"] div.stButton > button[data-testid="baseButton-secondary"]:hover {
    background: #f1f5f9 !important;
    border-color: #cbd5e1 !important;
    color: #0f172a !important;
}

/* Horizontal Radio Button Pills (去圓點膠囊化) */
div[data-testid="stRadio"] > div[role="radiogroup"][aria-orientation="horizontal"] > label > div:first-child {
    display: none !important;
}
div[data-testid="stRadio"] > div[role="radiogroup"][aria-orientation="horizontal"] > label {
    background: #f1f5f9;
    padding: 4px 12px !important;
    border-radius: 9999px !important;
    border: 1px solid #cbd5e1 !important;
    margin-right: 6px !important;
    cursor: pointer;
    transition: all 0.15s ease;
}
div[data-testid="stRadio"] > div[role="radiogroup"][aria-orientation="horizontal"] > label:hover {
    background: #e2e8f0;
}
div[data-testid="stRadio"] > div[role="radiogroup"][aria-orientation="horizontal"] > label:has(input:checked) {
    background: #2563eb !important;
    color: white !important;
    border-color: #1d4ed8 !important;
}
div[data-testid="stRadio"] > div[role="radiogroup"][aria-orientation="horizontal"] > label:has(input:checked) p {
    color: white !important;
    font-weight: 600;
}

/* Alerts */
div[data-testid="stAlert"] {
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* Reading Ergonomics & Line Spacing (LawyerMan / LawBank) */
p, div[data-testid="stMarkdownContainer"] p, div[data-testid="stMarkdownContainer"] li, textarea, .stTextArea textarea {
    line-height: 1.68 !important;
}
</style>
"""


def inject_global_styles() -> None:
    """Inject global scholarly CSS styling once per Streamlit render."""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def inject_reading_font_size(font_size: Optional[str] = None) -> None:
    """Inject dynamic reading font size CSS when larger than 16px default."""
    cur_fs = font_size if font_size is not None else st.session_state.get("reading_font_size", "16px")
    if cur_fs not in ("16px", "18px", "20px"):
        cur_fs = "16px"
    if cur_fs != "16px":
        st.markdown(
            f"""<style>
p, div[data-testid="stMarkdownContainer"] p, div[data-testid="stMarkdownContainer"] li, textarea, .stTextArea textarea {{
    font-size: {cur_fs} !important;
}}
</style>""",
            unsafe_allow_html=True,
        )
